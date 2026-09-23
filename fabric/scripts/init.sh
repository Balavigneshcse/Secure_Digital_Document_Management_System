#!/bin/bash
# Generates the consortium's identities (cryptogen) and the channel genesis block (configtxgen).
# Idempotent: does nothing if the artifacts volume is already populated.
set -euo pipefail
A=/artifacts
if [ -f "$A/.init-done" ]; then echo "[init] artifacts already present"; exit 0; fi
echo "[init] generating crypto material"
cryptogen generate --config=/config/crypto-config.yaml --output="$A/crypto"
echo "[init] generating channel genesis block"
FABRIC_CFG_PATH=/config configtxgen -profile SdmsChannel -outputBlock "$A/sdmschannel.block" -channelID sdmschannel
touch "$A/.init-done"
echo "[init] done"
