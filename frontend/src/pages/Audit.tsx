import { useState, type FormEvent } from "react";
import { api, fmtTime, shortHash, type ChainCheck, type VerifyT } from "../api";
import { Alert, Badge, Loading, Msg, useAction, useLoad } from "../ui";

const PAGE = 50;
const EMPTY = { actor: "", action: "", case_number: "", outcome: "", date_from: "", date_to: "" };
const outcomeKind = (o: string) => (o === "success" ? "ok" : o === "alert" ? "err" : "warn");

export function ChainResult({ r, what }: { r: ChainCheck; what: string }) {
  return r.ok ? (
    <Alert kind="ok">
      <strong>{what} intact.</strong> {r.checked} entries verified end to end.
      {r.last_anchor && <> Latest ledger anchor: audit entry #{r.last_anchor.audit_id} (<span className="mono">{shortHash(r.last_anchor.tx_id)}</span>).</>}
    </Alert>
  ) : (
    <Alert kind="err"><strong>{what} FAILED verification</strong> at #{r.broken_at ?? "?"}: {r.reason}</Alert>
  );
}

function DocumentCheck() {
  const [docId, setDocId] = useState("");
  const [ver, setVer] = useState("1");
  const [res, setRes] = useState<VerifyT | null>(null);
  const a = useAction();
  async function submit(e: FormEvent) {
    e.preventDefault();
    setRes((await a.run(() => api.verify(Number(docId), Number(ver)))) ?? null);
  }
  return (
    <form className="card" onSubmit={submit}>
      <h2>Check a document's integrity</h2>
      <p className="muted small" style={{ marginTop: -6 }}>Re-hashes the stored file and compares it with the database and the ledger. No document content is shown to auditors.</p>
      <Msg error={a.error} />
      <div className="row">
        <div><label htmlFor="did">Document ID</label><input id="did" inputMode="numeric" pattern="\d+" value={docId} onChange={(e) => setDocId(e.target.value)} required /></div>
        <div><label htmlFor="dv">Version</label><input id="dv" inputMode="numeric" pattern="\d+" value={ver} onChange={(e) => setVer(e.target.value)} required /></div>
        <div><button className="btn" disabled={a.busy}>{a.busy ? "Checking…" : "Verify"}</button></div>
      </div>
      {res && (res.status === "verified"
        ? <Alert kind="ok"><strong>Verified.</strong> File hash, database record and ledger anchor (block #{res.ledger_block}) all agree.</Alert>
        : <Alert kind="err"><strong>Tampering detected.</strong><ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{res.reasons.map((x) => <li key={x}>{x}</li>)}</ul></Alert>)}
    </form>
  );
}

export default function AuditPage() {
  const [draft, setDraft] = useState(EMPTY);
  const [applied, setApplied] = useState(EMPTY);
  const [offset, setOffset] = useState(0);
  const log = useLoad(() => api.audit({ ...applied, limit: PAGE, offset }), [applied, offset]);
  const [chain, setChain] = useState<ChainCheck | null>(null);
  const act = useAction();
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setDraft((s) => ({ ...s, [k]: e.target.value }));
  const total = log.data?.total ?? 0;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Audit log</h1>
          <div className="muted">Every login, view, download, edit, share and denied attempt — hash-chained so edits or deletions are detectable.</div>
        </div>
        <div className="actions">
          <button className="btn" disabled={act.busy} onClick={async () => setChain((await act.run(() => api.auditVerify())) ?? null)}>Verify audit chain</button>
          <button className="btn secondary" disabled={act.busy}
            onClick={() => act.run(() => api.auditAnchor(), (r) => r.skipped ?? `Audit head #${r.audit_id} anchored on the ledger (${shortHash(r.tx_id)}).`)}>
            Anchor to ledger
          </button>
          <button className="btn secondary" disabled={act.busy} onClick={() => act.run(() => api.auditExport(applied))}>Export CSV</button>
        </div>
      </div>

      <Msg error={act.error} ok={act.ok} />
      {chain && <ChainResult r={chain} what="Audit chain" />}
      <DocumentCheck />

      <form className="card" onSubmit={(e) => { e.preventDefault(); setOffset(0); setApplied(draft); }}>
        <div className="row">
          <div><label htmlFor="a1">Actor</label><input id="a1" value={draft.actor} onChange={set("actor")} placeholder="username" /></div>
          <div><label htmlFor="a2">Action</label><input id="a2" value={draft.action} onChange={set("action")} placeholder="e.g. DOCUMENT_DOWNLOADED" /></div>
          <div><label htmlFor="a3">Case number</label><input id="a3" value={draft.case_number} onChange={set("case_number")} /></div>
          <div>
            <label htmlFor="a4">Outcome</label>
            <select id="a4" value={draft.outcome} onChange={set("outcome")}>
              <option value="">Any</option><option>success</option><option>failure</option><option>denied</option><option>alert</option>
            </select>
          </div>
          <div><label htmlFor="a5">From</label><input id="a5" type="date" value={draft.date_from} onChange={set("date_from")} /></div>
          <div><label htmlFor="a6">To</label><input id="a6" type="date" value={draft.date_to} onChange={set("date_to")} /></div>
        </div>
        <div className="actions">
          <button className="btn">Filter</button>
          <button type="button" className="btn secondary" onClick={() => { setDraft(EMPTY); setApplied(EMPTY); setOffset(0); }}>Reset</button>
          <button type="button" className="btn secondary" onClick={() => log.reload()}>Refresh</button>
        </div>
      </form>

      <div className="card tablewrap">
        <Loading loading={log.loading && !log.data} error={log.error} />
        {log.data && (
          <>
            <table>
              <thead><tr><th>#</th><th>Time</th><th>Actor</th><th>Action</th><th>Case / resource</th><th>IP</th><th>Detail</th><th>Entry hash</th></tr></thead>
              <tbody>
                {log.data.items.map((e) => (
                  <tr key={e.id}>
                    <td>{e.id}</td>
                    <td className="small">{fmtTime(e.ts)}</td>
                    <td>{e.actor_username ?? "—"}{e.actor_role && <div className="muted small">{e.actor_role}</div>}</td>
                    <td><Badge kind={outcomeKind(e.outcome)}>{e.action}</Badge></td>
                    <td className="small">{e.case_number ?? ""}{e.resource_type && <div className="muted">{e.resource_type} {e.resource_id}</div>}</td>
                    <td className="mono">{e.ip ?? "—"}</td>
                    <td className="small">
                      {Object.keys(e.detail).length ? <details><summary>view</summary><pre>{JSON.stringify(e.detail, null, 2)}</pre></details> : "—"}
                    </td>
                    <td className="mono" title={`prev ${e.prev_hash}\nthis ${e.entry_hash}`}>{shortHash(e.entry_hash, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {log.data.items.length === 0 && <div className="muted">No entries match.</div>}
            <div className="actions" style={{ marginTop: 12, justifyContent: "space-between" }}>
              <span className="muted small">{total ? `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}` : "0 entries"}</span>
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
