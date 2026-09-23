'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const grpc = require('@grpc/grpc-js');
const { connect, signers } = require('@hyperledger/fabric-gateway');
const { common } = require('@hyperledger/fabric-protos');
const { decodeBlock, verifyBlocks, hex } = require('./blocks');

const ARTIFACTS = process.env.ARTIFACTS_DIR || '/artifacts';
const ORG = process.env.FABRIC_ORG || 'police';
const MSP_ID = process.env.FABRIC_MSP || 'PoliceMSP';
const CHANNEL = process.env.FABRIC_CHANNEL || 'sdmschannel';
const CHAINCODE = process.env.FABRIC_CHAINCODE || 'anchor';
const PEER_HOST = process.env.PEER_HOST || `peer0.${ORG}.sdms.local`;
const PEER_ENDPOINT = process.env.PEER_ENDPOINT || `${PEER_HOST}:7051`;
const MAX_CACHED_BLOCKS = 20000;

const firstFile = (dir) => path.join(dir, fs.readdirSync(dir)[0]);
const decoder = new TextDecoder();
const asText = (u8) => decoder.decode(u8);

class NotFound extends Error {}

class FabricLedger {
  constructor() {
    const org = path.join(ARTIFACTS, 'crypto', 'peerOrganizations', `${ORG}.sdms.local`);
    const tlsCa = fs.readFileSync(path.join(org, 'peers', PEER_HOST, 'tls', 'ca.crt'));
    const user = path.join(org, 'users', `User1@${ORG}.sdms.local`, 'msp');
    const cert = fs.readFileSync(firstFile(path.join(user, 'signcerts')));
    const key = fs.readFileSync(firstFile(path.join(user, 'keystore')));

    this.client = new grpc.Client(PEER_ENDPOINT, grpc.credentials.createSsl(tlsCa));
    this.gateway = connect({
      client: this.client,
      identity: { mspId: MSP_ID, credentials: cert },
      signer: signers.newPrivateKeySigner(crypto.createPrivateKey(key)),
      evaluateOptions: () => ({ deadline: Date.now() + 10_000 }),
      endorseOptions: () => ({ deadline: Date.now() + 25_000 }),
      submitOptions: () => ({ deadline: Date.now() + 15_000 }),
      commitStatusOptions: () => ({ deadline: Date.now() + 60_000 }),
    });
    const network = this.gateway.getNetwork(CHANNEL);
    this.contract = network.getContract(CHAINCODE);
    this.qscc = network.getContract('qscc');
    this.blockCache = new Map(); // block number -> decoded block (blocks are immutable once committed)
    this.txBlock = new Map(); //   tx id -> block number
  }

  close() {
    this.gateway.close();
    this.client.close();
  }

  // ---- blocks (qscc) ------------------------------------------------------------------------
  async chainInfo() {
    const info = common.BlockchainInfo.deserializeBinary(await this.qscc.evaluateTransaction('GetChainInfo', CHANNEL));
    const cur = info.getCurrentblockhash_asU8 ? info.getCurrentblockhash_asU8() : info.getCurrentBlockHash_asU8();
    return { height: Number(info.getHeight()), currentBlockHash: hex(cur) };
  }

  _remember(b) {
    if (this.blockCache.size >= MAX_CACHED_BLOCKS) this.blockCache.delete(this.blockCache.keys().next().value);
    this.blockCache.set(b.number, b);
    b.txs.forEach((t) => t.tx_id && this.txBlock.set(t.tx_id, b.number));
    return b;
  }

  async block(number) {
    const hit = this.blockCache.get(number);
    if (hit) return hit;
    const bytes = await this.qscc.evaluateTransaction('GetBlockByNumber', CHANNEL, String(number));
    return this._remember(decodeBlock(bytes));
  }

  async blockOfTx(txId) {
    if (this.txBlock.has(txId)) return this.block(this.txBlock.get(txId));
    const bytes = await this.qscc.evaluateTransaction('GetBlockByTxID', CHANNEL, txId);
    return this._remember(decodeBlock(bytes));
  }

  async allBlocks() {
    const { height, currentBlockHash } = await this.chainInfo();
    const blocks = [];
    for (let i = 0; i < height; i++) blocks.push(await this.block(i));
    return { blocks, currentBlockHash };
  }

  // ---- anchors --------------------------------------------------------------------------------
  _view(rec, block) {
    return {
      index: block.number,
      ts: rec.ts,
      kind: rec.kind,
      payload: JSON.parse(rec.payload_json),
      payload_hash: rec.payload_hash,
      prev_hash: block.prevHash,
      block_hash: block.hash,
      tx_id: rec.tx_id,
      msp: rec.msp,
    };
  }

  async anchor(kind, payloadJson) {
    const proposal = this.contract.newProposal('RecordAnchor', { arguments: [kind, payloadJson] });
    const endorsed = await proposal.endorse();
    const submitted = await endorsed.submit();
    const status = await submitted.getStatus();
    if (!status.successful) {
      throw new Error(`transaction ${status.transactionId} was not committed (validation code ${status.code})`);
    }
    const result = JSON.parse(asText(submitted.getResult()));
    const block = await this.block(Number(status.blockNumber));
    return this._view({ tx_id: result.tx_id, kind, payload_json: payloadJson, payload_hash: result.payload_hash, ts: result.ts, msp: result.msp }, block);
  }

  async getByTx(txId) {
    if (!/^[0-9a-f]{64}$/.test(txId)) throw new NotFound('malformed transaction id');
    let raw;
    try {
      raw = await this.contract.evaluateTransaction('GetAnchor', txId);
    } catch (e) {
      if (/no anchor for transaction/i.test(String(e.message)) || /no anchor for transaction/i.test(JSON.stringify(e.details || []))) throw new NotFound('no such anchor');
      throw e;
    }
    const rec = JSON.parse(asText(raw));
    return this._view(rec, await this.blockOfTx(txId));
  }

  async latest(kind, scope) {
    if (!/^[A-Z][A-Z0-9_]{2,31}$/.test(kind)) throw new NotFound('bad kind');
    if (scope && !/^[0-9a-f]{32}$/.test(scope)) throw new NotFound('bad scope');
    const txId = asText(await this.contract.evaluateTransaction('GetLatest', kind, scope || '')).trim();
    if (!txId) throw new NotFound('none');
    return this.getByTx(txId);
  }

  /** Anchors as recorded in the blocks themselves (newest first), read from the chain rather than world state. */
  async list({ offset = 0, limit = 50, kind = null }) {
    const { blocks } = await this.allBlocks();
    const rows = [];
    for (const b of blocks) {
      if (b.number === 0) {
        rows.push({ index: 0, ts: b.txs[0]?.ts || null, kind: 'GENESIS', payload: { note: 'channel genesis block' }, payload_hash: b.dataHash, prev_hash: b.prevHash, block_hash: b.hash, tx_id: b.hash, msp: null });
        continue;
      }
      for (const t of b.txs) {
        if (!t.valid || t.chaincode !== CHAINCODE || t.args[0] !== 'RecordAnchor') continue;
        let payload;
        try { payload = JSON.parse(t.args[2]); } catch { continue; }
        rows.push({
          index: b.number, ts: t.ts, kind: t.args[1], payload,
          payload_hash: crypto.createHash('sha256').update(t.args[2], 'utf8').digest('hex'),
          prev_hash: b.prevHash, block_hash: b.hash, tx_id: t.tx_id, msp: null,
        });
      }
    }
    const filtered = rows.filter((r) => !kind || r.kind === kind).reverse();
    return { total: filtered.length, items: filtered.slice(offset, offset + limit) };
  }

  async verify() {
    const { blocks, currentBlockHash } = await this.allBlocks();
    return verifyBlocks(blocks, currentBlockHash);
  }

  async status() {
    const info = await this.chainInfo();
    return { backend: 'fabric', channel: CHANNEL, chaincode: CHAINCODE, org: MSP_ID, peer: PEER_ENDPOINT, height: info.height, current_block_hash: info.currentBlockHash };
  }
}

module.exports = { FabricLedger, NotFound };
