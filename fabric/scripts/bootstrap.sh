#!/bin/bash
# Brings the SDMS Fabric network to a usable state: channel created, both peers joined, the `anchor`
# chaincode (chaincode-as-a-service) installed, approved by both orgs and committed, smoke-tested.
# Idempotent - safe to re-run.
set -uo pipefail

A=/artifacts
C=$A/crypto
ORD=orderer.sdms.local
ORD_TLS=$C/ordererOrganizations/sdms.local/orderers/$ORD/tls
CH=sdmschannel
CC=anchor
CC_VER=1.0
CC_SEQ=1
TLS_POLICE=$C/peerOrganizations/police.sdms.local/peers/peer0.police.sdms.local/tls/ca.crt
TLS_COURT=$C/peerOrganizations/court.sdms.local/peers/peer0.court.sdms.local/tls/ca.crt

log() { echo "[bootstrap] $*"; }
die() { echo "[bootstrap] FATAL: $*" >&2; exit 1; }

if [ -f "$A/.bootstrap-done" ]; then log "already bootstrapped"; exit 0; fi

use_org() {  # police | court  -> peer CLI acts as that org's admin against its peer
  local org=$1 Org
  Org="$(tr '[:lower:]' '[:upper:]' <<< "${org:0:1}")${org:1}"
  export CORE_PEER_TLS_ENABLED=true
  export CORE_PEER_LOCALMSPID="${Org}MSP"
  export CORE_PEER_TLS_ROOTCERT_FILE=$C/peerOrganizations/$org.sdms.local/peers/peer0.$org.sdms.local/tls/ca.crt
  export CORE_PEER_MSPCONFIGPATH=$C/peerOrganizations/$org.sdms.local/users/Admin@$org.sdms.local/msp
  export CORE_PEER_ADDRESS=peer0.$org.sdms.local:7051
}

retry() {  # retry <attempts> <sleep> <cmd...>
  local n=$1 s=$2; shift 2
  for i in $(seq 1 "$n"); do "$@" && return 0; sleep "$s"; done
  return 1
}

osn() { osnadmin "$@" -o $ORD:7053 --ca-file $ORD_TLS/ca.crt --client-cert $ORD_TLS/server.crt --client-key $ORD_TLS/server.key; }

# ---- 1. orderer channel ------------------------------------------------------------------------
log "waiting for the orderer admin endpoint"
retry 60 2 osn channel list >/dev/null 2>&1 || die "orderer admin endpoint never came up"
if osn channel list 2>&1 | grep -q "\"name\": *\"$CH\""; then
  log "channel $CH already exists on the orderer"
else
  log "creating channel $CH"
  retry 5 3 osn channel join --channelID $CH --config-block $A/$CH.block >/dev/null 2>&1 || die "channel join on orderer failed"
fi

# ---- 2. peers join ----------------------------------------------------------------------------
for org in police court; do
  use_org $org
  log "waiting for peer0.$org"
  retry 60 2 peer channel list >/dev/null 2>&1 || die "peer0.$org never came up"
  if peer channel list 2>&1 | grep -q "$CH"; then
    log "peer0.$org already joined"
  else
    log "peer0.$org joining $CH"
    retry 10 3 peer channel join -b $A/$CH.block >/dev/null 2>&1 || die "peer0.$org could not join"
  fi
done

# ---- 3. chaincode package (chaincode-as-a-service) --------------------------------------------
PKG=$A/$CC.tgz
if [ ! -f "$PKG" ]; then
  log "packaging chaincode-as-a-service definition"
  W=$(mktemp -d); pushd "$W" >/dev/null
  echo '{"address":"anchor-cc:9999","dial_timeout":"10s","tls_required":false}' > connection.json
  tar czf code.tar.gz connection.json
  echo "{\"type\":\"ccaas\",\"label\":\"${CC}_${CC_VER}\"}" > metadata.json
  tar czf "$PKG" code.tar.gz metadata.json
  popd >/dev/null
fi
PKG_ID=$(peer lifecycle chaincode calculatepackageid "$PKG") || die "cannot compute package id"
echo -n "$PKG_ID" > $A/$CC.ccid          # the chaincode container waits for this file, then starts serving
log "package id: $PKG_ID"

# ---- 4. install + approve on both orgs --------------------------------------------------------
for org in police court; do
  use_org $org
  if peer lifecycle chaincode queryinstalled 2>&1 | grep -q "$PKG_ID"; then
    log "$org: already installed"
  else
    log "$org: installing"
    retry 5 3 peer lifecycle chaincode install "$PKG" >/dev/null 2>&1 || die "$org: install failed"
  fi
  log "$org: approving definition"
  retry 5 3 peer lifecycle chaincode approveformyorg -o $ORD:7050 --ordererTLSHostnameOverride $ORD --tls --cafile $ORD_TLS/ca.crt \
    --channelID $CH --name $CC --version $CC_VER --package-id "$PKG_ID" --sequence $CC_SEQ >/dev/null 2>&1 || die "$org: approve failed"
done

# ---- 5. commit (needs both orgs' approvals) ---------------------------------------------------
use_org police
if peer lifecycle chaincode querycommitted -C $CH -n $CC 2>&1 | grep -q "Version: $CC_VER"; then
  log "chaincode already committed"
else
  log "committing chaincode definition"
  retry 5 3 peer lifecycle chaincode commit -o $ORD:7050 --ordererTLSHostnameOverride $ORD --tls --cafile $ORD_TLS/ca.crt \
    --channelID $CH --name $CC --version $CC_VER --sequence $CC_SEQ \
    --peerAddresses peer0.police.sdms.local:7051 --tlsRootCertFiles $TLS_POLICE \
    --peerAddresses peer0.court.sdms.local:7051 --tlsRootCertFiles $TLS_COURT >/dev/null 2>&1 || die "commit failed"
fi

# ---- 6. smoke test: a transaction endorsed by BOTH orgs ---------------------------------------
log "smoke test: recording a bootstrap anchor (endorsed by police + court)"
smoke() {
  peer chaincode invoke -o $ORD:7050 --ordererTLSHostnameOverride $ORD --tls --cafile $ORD_TLS/ca.crt -C $CH -n $CC \
    --peerAddresses peer0.police.sdms.local:7051 --tlsRootCertFiles $TLS_POLICE \
    --peerAddresses peer0.court.sdms.local:7051 --tlsRootCertFiles $TLS_COURT --waitForEvent \
    -c '{"function":"RecordAnchor","Args":["NETWORK_BOOTSTRAP","{\"note\":\"sdms fabric network bootstrapped\"}"]}' 2>&1
}
OUT=""
for i in $(seq 1 30); do
  OUT=$(smoke) && { log "smoke test OK"; break; }
  sleep 3
done
echo "$OUT" | grep -q "status:200" || { echo "$OUT" | tail -5; die "smoke test failed"; }

touch $A/.bootstrap-done
log "network ready"
