'use strict';

// Decoding and independent verification of Fabric blocks (as returned by the `qscc` system chaincode).
const crypto = require('crypto');
const { common, peer } = require('@hyperledger/fabric-protos');

const sha256 = (...bufs) => {
  const h = crypto.createHash('sha256');
  bufs.forEach((b) => h.update(b));
  return h.digest();
};
const hex = (u8) => Buffer.from(u8).toString('hex');

// --- ASN.1 DER, as Fabric hashes block headers: SEQUENCE { INTEGER number, OCTET STRING prev, OCTET STRING data } ---
function derLen(n) {
  if (n < 0x80) return Buffer.from([n]);
  const bytes = [];
  while (n > 0) { bytes.unshift(n & 0xff); n = Math.floor(n / 256); }
  return Buffer.from([0x80 | bytes.length, ...bytes]);
}
function derInteger(num) {
  let h = BigInt(num).toString(16);
  if (h.length % 2) h = '0' + h;
  let b = Buffer.from(h, 'hex');
  if (b[0] & 0x80) b = Buffer.concat([Buffer.from([0]), b]);
  return Buffer.concat([Buffer.from([0x02]), derLen(b.length), b]);
}
const derOctet = (b) => Buffer.concat([Buffer.from([0x04]), derLen(b.length), Buffer.from(b)]);
const derSequence = (...items) => {
  const body = Buffer.concat(items);
  return Buffer.concat([Buffer.from([0x30]), derLen(body.length), body]);
};

/** Hash of a block header, exactly as Fabric computes it (this is what the next block's previous_hash holds). */
function headerHash(number, previousHash, dataHash) {
  return sha256(derSequence(derInteger(number), derOctet(previousHash), derOctet(dataHash)));
}

function tsToIso(ts) {
  if (!ts) return null;
  return new Date(ts.getSeconds() * 1000 + Math.floor(ts.getNanos() / 1e6)).toISOString();
}

/** Decodes a serialized common.Block into a plain object (header hashes + the transactions it carries). */
function decodeBlock(bytes) {
  const block = common.Block.deserializeBinary(bytes);
  const header = block.getHeader();
  const number = Number(header.getNumber());
  const prev = header.getPreviousHash_asU8();
  const dataHash = header.getDataHash_asU8();
  const envelopes = block.getData().getDataList_asU8();
  const flags = block.getMetadata().getMetadataList_asU8()[common.BlockMetadataIndex.TRANSACTIONS_FILTER] || new Uint8Array();

  const txs = envelopes.map((envBytes, i) => {
    const out = { tx_id: '', ts: null, type: null, valid: (flags[i] ?? 0) === peer.TxValidationCode.VALID, chaincode: null, args: [] };
    try {
      const payload = common.Payload.deserializeBinary(common.Envelope.deserializeBinary(envBytes).getPayload_asU8());
      const chdr = common.ChannelHeader.deserializeBinary(payload.getHeader().getChannelHeader_asU8());
      out.tx_id = chdr.getTxId();
      out.ts = tsToIso(chdr.getTimestamp());
      out.type = chdr.getType();
      if (out.type === common.HeaderType.ENDORSER_TRANSACTION) {
        const action = peer.Transaction.deserializeBinary(payload.getData_asU8()).getActionsList()[0];
        const cap = peer.ChaincodeActionPayload.deserializeBinary(action.getPayload_asU8());
        const prp = peer.ChaincodeProposalPayload.deserializeBinary(cap.getChaincodeProposalPayload_asU8());
        const spec = peer.ChaincodeInvocationSpec.deserializeBinary(prp.getInput_asU8()).getChaincodeSpec();
        out.chaincode = spec.getChaincodeId().getName();
        out.args = spec.getInput().getArgsList_asU8().map((a) => Buffer.from(a).toString('utf8'));
      }
    } catch (e) {
      out.error = String(e.message || e);
    }
    return out;
  });

  return { number, hash: hex(headerHash(number, prev, dataHash)), prevHash: hex(prev), dataHash: hex(dataHash), envelopes, txs };
}

/** Checks every block links to its predecessor and that each header's data hash matches its content. */
function verifyBlocks(blocks, currentBlockHash) {
  let prevHash = '';
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    if (b.number !== i) return { ok: false, checked: i, broken_at: i, reason: 'missing block' };
    if (i > 0 && b.prevHash !== prevHash) return { ok: false, checked: i, broken_at: i, reason: 'broken hash link' };
    if (hex(sha256(...b.envelopes)) !== b.dataHash) return { ok: false, checked: i, broken_at: i, reason: 'block content altered' };
    prevHash = b.hash;
  }
  if (currentBlockHash && blocks.length && prevHash !== currentBlockHash) {
    return { ok: false, checked: blocks.length, broken_at: blocks.length - 1, reason: 'tip does not match the peer-reported chain head' };
  }
  return { ok: true, checked: blocks.length, broken_at: null, reason: null };
}

module.exports = { decodeBlock, verifyBlocks, headerHash, derInteger, derOctet, derSequence, sha256, hex };
