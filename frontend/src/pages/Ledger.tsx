import { useState } from "react";
import { api, fmtTime, shortHash, type ChainCheck } from "../api";
import { Badge, Loading, Msg, useAction, useLoad } from "../ui";
import { ChainResult } from "./Audit";

const PAGE = 25;
const KINDS = ["", "DOC_VERSION", "AUDIT_ANCHOR", "GENESIS"];

export default function LedgerPage() {
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const blocks = useLoad(() => api.blocks({ kind: kind || undefined, limit: PAGE, offset }), [kind, offset]);
  const [chain, setChain] = useState<ChainCheck | null>(null);
  const status = useLoad(() => api.ledgerStatus(), []);
  const act = useAction();
  const total = blocks.data?.total ?? 0;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Integrity ledger</h1>
          <div className="muted">Append-only chain of document-version hashes and audit-log anchors. Only hashes and minimal metadata are stored here — never document content.</div>
        </div>
        <button className="btn" disabled={act.busy} onClick={async () => setChain((await act.run(() => api.ledgerVerify())) ?? null)}>
          {act.busy ? "Verifying…" : "Verify full chain"}
        </button>
      </div>

      <Msg error={act.error} />
      {status.data && (
        <div className="card">
          <dl className="kv">
            <dt>Ledger</dt>
            <dd>
              {status.data.backend === "fabric" ? <Badge kind="ok">Hyperledger Fabric</Badge> : <Badge kind="warn">in-memory (testing only — not durable)</Badge>}
              {status.data.org && <span className="muted"> · connected as {status.data.org}</span>}
            </dd>
            {status.data.channel && <><dt>Channel / chaincode</dt><dd>{status.data.channel} / {status.data.chaincode}</dd></>}
            <dt>Chain height</dt><dd>{status.data.height} blocks</dd>
            {status.data.current_block_hash && <><dt>Chain head</dt><dd className="mono hash">{status.data.current_block_hash}</dd></>}
          </dl>
          {status.data.backend === "fabric" && <div className="muted small">Every anchor is endorsed by both the Police and Court organisations before it is written; the chain is held by the peers, not by this application.</div>}
        </div>
      )}
      {chain && <ChainResult r={chain} what="Ledger chain" />}

      <div className="card">
        <label htmlFor="k">Block type</label>
        <select id="k" value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0); }} style={{ maxWidth: 240 }}>
          {KINDS.map((k) => <option key={k} value={k}>{k || "All"}</option>)}
        </select>
      </div>

      <div className="card tablewrap">
        <Loading loading={blocks.loading && !blocks.data} error={blocks.error} />
        {blocks.data && (
          <>
            <table>
              <thead><tr><th>Block</th><th>Time</th><th>Type</th><th>Tx / block hash</th><th>Previous hash</th><th>Payload</th></tr></thead>
              <tbody>
                {blocks.data.items.map((b) => (
                  <tr key={b.index}>
                    <td>#{b.index}</td>
                    <td className="small">{fmtTime(b.ts)}</td>
                    <td><Badge>{b.kind}</Badge></td>
                    <td className="mono" title={b.tx_id}>{shortHash(b.tx_id, 12)}</td>
                    <td className="mono" title={b.prev_hash}>{shortHash(b.prev_hash, 12)}</td>
                    <td className="small"><details><summary>view</summary><pre>{JSON.stringify(b.payload, null, 2)}</pre></details></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="actions" style={{ marginTop: 12, justifyContent: "space-between" }}>
              <span className="muted small">{total ? `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}` : "0 blocks"}</span>
              <span className="actions">
                <button className="btn secondary small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Newer</button>
                <button className="btn secondary small" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Older →</button>
              </span>
            </div>
          </>
        )}
      </div>
    </>
  );
}
