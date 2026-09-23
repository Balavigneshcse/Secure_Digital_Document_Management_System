import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, DOC_TYPES, fmtTime, hasContentAccess, label, type SearchResult } from "../api";
import { useAuth } from "../auth";
import { Loading, Msg, useAction } from "../ui";

const EMPTY = { q: "", case_number: "", fir_number: "", party: "", doc_type: "", date_from: "", date_to: "" };

export default function SearchPage() {
  const { user } = useAuth();
  const canSeeContent = hasContentAccess(user);
  const [f, setF] = useState(EMPTY);
  const [semantic, setSemantic] = useState(false);
  const [res, setRes] = useState<SearchResult | null>(null);
  const { busy, error, run } = useAction();
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const params: Record<string, string | undefined> = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() || undefined]));
    if (semantic) params.semantic = "true";
    const r = await run(() => api.search(params));
    if (r) setRes(r);
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Search</h1>
          <div className="muted">
            {canSeeContent
              ? "Full-text (incl. OCR'd content), case number, FIR, names, section of law and filing date — across cases you have access to."
              : "Case metadata search across your station. Document titles and content are not searchable by station admins."}
          </div>
        </div>
      </div>

      <form className="card" onSubmit={submit}>
        <div className="row">
          <div><label htmlFor="q">Keyword{canSeeContent ? " / section / text" : ""}</label><input id="q" value={f.q} onChange={set("q")} maxLength={200} autoFocus /></div>
          <div><label htmlFor="cn">Case number</label><input id="cn" value={f.case_number} onChange={set("case_number")} /></div>
          <div><label htmlFor="fn">FIR number</label><input id="fn" value={f.fir_number} onChange={set("fir_number")} /></div>
          <div><label htmlFor="pn">Person / party name</label><input id="pn" value={f.party} onChange={set("party")} /></div>
        </div>
        {canSeeContent && (
          <div className="row">
            <div>
              <label htmlFor="ty">Document type</label>
              <select id="ty" value={f.doc_type} onChange={set("doc_type")}>
                <option value="">Any</option>
                {DOC_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
              </select>
            </div>
            <div><label htmlFor="df">Filed from</label><input id="df" type="date" value={f.date_from} onChange={set("date_from")} /></div>
            <div><label htmlFor="dto">Filed to</label><input id="dto" type="date" value={f.date_to} onChange={set("date_to")} /></div>
          </div>
        )}
        {canSeeContent && (
          <label style={{ fontWeight: 400, color: "inherit", marginBottom: 12 }}>
            <input type="checkbox" style={{ width: "auto", marginRight: 6 }} checked={semantic} onChange={(e) => setSemantic(e.target.checked)} />
            Search by meaning (AI) — finds related documents even when the words differ; uses the keyword box only, in English, Hindi or Tamil
          </label>
        )}
        <div className="actions">
          <button className="btn" disabled={busy}>{busy ? "Searching…" : "Search"}</button>
          <button type="button" className="btn secondary" onClick={() => { setF(EMPTY); setRes(null); }}>Clear</button>
        </div>
      </form>

      <Msg error={error} />
      <Loading loading={busy} error={null} />

      {res && (
        <>
          <div className="card tablewrap">
            <h2>Cases ({res.cases.length})</h2>
            {res.cases.length === 0 ? <div className="muted">No matching cases.</div> : (
              <table>
                <thead><tr><th>Case no.</th><th>Title</th><th>FIR</th><th>Parties</th></tr></thead>
                <tbody>
                  {res.cases.map((c) => (
                    <tr key={c.id}>
                      <td className="mono"><Link to={`/cases/${c.id}`}>{c.case_number}</Link></td>
                      <td>{c.title}</td><td>{c.fir_number ?? "—"}</td><td>{c.parties.join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {canSeeContent && (
            <div className="card tablewrap">
              <h2>Documents ({res.documents_total ?? 0})</h2>
              {res.documents.length === 0 ? <div className="muted">No matching documents.</div> : (
                <table>
                  <thead><tr><th>Document</th><th>Type</th><th>Case</th><th>Filed</th></tr></thead>
                  <tbody>
                    {res.documents.map((d) => (
                      <tr key={d.document_id}>
                        <td>
                          <Link to={`/documents/${d.document_id}`}>{d.title}</Link> <span className="muted small">v{d.version_no}</span>
                          {d.score != null && <> <span className="badge">{Math.round(d.score * 100)}% match</span></>}
                          {d.snippet && <div className="small muted">{d.snippet}</div>}
                        </td>
                        <td>{label(d.doc_type)}</td>
                        <td className="mono"><Link to={`/cases/${d.case_id}`}>{d.case_number}</Link></td>
                        <td>{fmtTime(d.uploaded_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}
