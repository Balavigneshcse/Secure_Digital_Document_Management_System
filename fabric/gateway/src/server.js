'use strict';

const crypto = require('crypto');
const fs = require('fs');
const express = require('express');
const { FabricLedger, NotFound } = require('./ledger');

const PORT = Number(process.env.PORT || 8088);
const KEY = process.env.GATEWAY_KEY || '';
const READY_FILE = `${process.env.ARTIFACTS_DIR || '/artifacts'}/.bootstrap-done`;

if (KEY.length < 16) {
  console.error('GATEWAY_KEY must be set (16+ chars)');
  process.exit(1);
}

let ledger = null;
let lastError = 'starting';

async function connectWhenReady() {
  for (;;) {
    try {
      if (!fs.existsSync(READY_FILE)) throw new Error('waiting for the network bootstrap to finish');
      const l = new FabricLedger();
      await l.status(); // proves the peer answers and the identity is accepted
      ledger = l;
      lastError = null;
      console.log('connected to Fabric');
      return;
    } catch (e) {
      lastError = String(e.message || e);
      console.log('not connected yet:', lastError);
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
}

const safeEqual = (a, b) => {
  const x = Buffer.from(String(a)), y = Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
};

const app = express();
app.use(express.json({ limit: '64kb' }));

app.get('/health', (req, res) => res.status(ledger ? 200 : 503).json({ ok: !!ledger, error: lastError }));

app.use((req, res, next) => {
  if (!safeEqual(req.get('x-gateway-key') || '', KEY)) return res.status(401).json({ error: 'unauthorized' });
  if (!ledger) return res.status(503).json({ error: `ledger not ready: ${lastError}` });
  next();
});

const wrap = (fn) => async (req, res) => {
  try {
    res.json(await fn(req));
  } catch (e) {
    if (e instanceof NotFound) return res.status(404).json({ error: e.message });
    if (e.status) return res.status(e.status).json({ error: e.message });
    // Fabric wraps chaincode rejections ("failed to endorse ... see attached details"); surface the real reason.
    const detail = Array.isArray(e.details) ? e.details.map((d) => d.message).filter(Boolean).join('; ') : '';
    console.error(e.message, detail);
    res.status(502).json({ error: `${e.message}${detail ? ` :: ${detail}` : ''}`.slice(0, 600) });
  }
};

app.post('/anchor', wrap(async (req) => {
  const { kind, payload_json: payloadJson } = req.body || {};
  if (typeof kind !== 'string' || typeof payloadJson !== 'string') throw Object.assign(new Error('kind and payload_json (strings) are required'), { status: 400 });
  return ledger.anchor(kind, payloadJson);
}));
app.get('/tx/:id', wrap((req) => ledger.getByTx(req.params.id)));
app.get('/latest/:kind', wrap((req) => ledger.latest(req.params.kind, req.query.scope || '')));
app.get('/blocks', wrap((req) => ledger.list({
  offset: Math.max(0, parseInt(req.query.offset || '0', 10) || 0),
  limit: Math.min(200, Math.max(1, parseInt(req.query.limit || '50', 10) || 50)),
  kind: req.query.kind || null,
})));
app.get('/verify', wrap(() => ledger.verify()));
app.get('/status', wrap(() => ledger.status()));

app.listen(PORT, () => console.log(`ledger gateway listening on :${PORT}`));
connectWhenReady();
