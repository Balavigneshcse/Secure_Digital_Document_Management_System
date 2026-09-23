'use strict';

const crypto = require('crypto');
const { Contract } = require('fabric-contract-api');

// Only the two consortium organisations may write. (Channel membership already limits who can connect;
// this is defence in depth and records who anchored what.)
const WRITER_MSPS = new Set(['PoliceMSP', 'CourtMSP']);
const KIND_RE = /^[A-Z][A-Z0-9_]{2,31}$/;
const MAX_PAYLOAD_BYTES = 16 * 1024;

/**
 * Append-only anchor registry. The backend sends the SHA-256 hash and minimal metadata of each document
 * version (kind DOC_VERSION) and the head hash of its audit log (kind AUDIT_ANCHOR). Documents and names
 * never reach the ledger. No function here updates or deletes an anchor: a record, once written, can only be
 * read - and Fabric keeps the full transaction history on every peer regardless.
 */
class AnchorContract extends Contract {
  constructor() {
    super('AnchorContract');
  }

  /** Records `payloadJson` (a JSON object, sent as the exact string the caller hashed) under this transaction. */
  async RecordAnchor(ctx, kind, payloadJson) {
    const msp = ctx.clientIdentity.getMSPID();
    if (!WRITER_MSPS.has(msp)) throw new Error(`organisation ${msp} may not record anchors`);
    if (!KIND_RE.test(kind)) throw new Error('kind must be UPPER_SNAKE_CASE (3-32 chars)');
    if (typeof payloadJson !== 'string' || Buffer.byteLength(payloadJson, 'utf8') > MAX_PAYLOAD_BYTES) {
      throw new Error(`payload must be a string of at most ${MAX_PAYLOAD_BYTES} bytes`);
    }
    let payload;
    try {
      payload = JSON.parse(payloadJson);
    } catch (e) {
      throw new Error('payload is not valid JSON');
    }
    if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error('payload must be a JSON object');
    }

    const txId = ctx.stub.getTxID();
    const t = ctx.stub.getTxTimestamp();
    const ts = new Date(Number(t.seconds.toString()) * 1000 + Math.floor(t.nanos / 1e6)).toISOString();
    const payloadHash = crypto.createHash('sha256').update(payloadJson, 'utf8').digest('hex');

    if (kind === 'DOC_VERSION') {
      if (!/^[0-9a-f]{32}$/.test(payload.document_uid || '') || !Number.isInteger(payload.version_no) || !/^[0-9a-f]{64}$/.test(payload.sha256 || '')) {
        throw new Error('DOC_VERSION needs document_uid (32 hex), an integer version_no and a hex sha256');
      }
      // Keyed on the globally unique document uid (not a database serial id): a version can be anchored exactly once.
      const docKey = `DOC~${payload.document_uid}~${payload.version_no}`;
      if ((await ctx.stub.getState(docKey)).length > 0) {
        throw new Error(`document ${payload.document_uid} version ${payload.version_no} is already anchored`);
      }
      await ctx.stub.putState(docKey, Buffer.from(txId));
    }

    if (kind === 'AUDIT_ANCHOR') {
      // Several SDMS deployments may share this ledger; each audit chain is identified by its own chain_id.
      if (!/^[0-9a-f]{32}$/.test(payload.chain_id || '')) throw new Error('AUDIT_ANCHOR needs chain_id (32 hex)');
      await ctx.stub.putState(`LATEST~AUDIT_ANCHOR~${payload.chain_id}`, Buffer.from(txId));
    }

    const record = { tx_id: txId, kind, payload_json: payloadJson, payload_hash: payloadHash, ts, msp };
    await ctx.stub.putState(`ANCHOR~${txId}`, Buffer.from(JSON.stringify(record)));
    // Blind write (never read here): concurrent anchors don't conflict; the last one committed wins.
    await ctx.stub.putState(`LATEST~${kind}`, Buffer.from(txId));

    return JSON.stringify({ tx_id: txId, ts, payload_hash: payloadHash, msp });
  }

  /** The anchor recorded by transaction `txId`. */
  async GetAnchor(ctx, txId) {
    const raw = await ctx.stub.getState(`ANCHOR~${txId}`);
    if (!raw || raw.length === 0) throw new Error(`no anchor for transaction ${txId}`);
    return raw.toString('utf8');
  }

  /** Transaction id of the most recent anchor of this kind (optionally within one scope, e.g. an audit chain), or ''. */
  async GetLatest(ctx, kind, scope) {
    const raw = await ctx.stub.getState(scope ? `LATEST~${kind}~${scope}` : `LATEST~${kind}`);
    return raw && raw.length ? raw.toString('utf8') : '';
  }

  /** The anchor for a document version, or throws if that version was never anchored. */
  async GetDocumentAnchor(ctx, documentUid, versionNo) {
    const tx = await ctx.stub.getState(`DOC~${documentUid}~${versionNo}`);
    if (!tx || tx.length === 0) throw new Error(`document ${documentUid} version ${versionNo} is not anchored`);
    return this.GetAnchor(ctx, tx.toString('utf8'));
  }
}

module.exports = AnchorContract;
