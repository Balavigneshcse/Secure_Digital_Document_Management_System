import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, canWrite, DOC_TYPES, fmtSize, fmtTime, hasContentAccess, label, shortHash, type CaseSummary, type CaseT, type DocumentT, type User } from "../api";
import { useAuth } from "../auth";
import { Alert, Badge, Loading, Msg, useAction, useLoad } from "../ui";

function UploadForm({ caseId, onUploaded }: { caseId: number; onUploaded: (d: DocumentT) => void }) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState("auto");
  const [desc, setDesc] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const { busy, error, ok, run } = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.set("title", title.trim());
    fd.set("doc_type", type);
    if (desc.trim()) fd.set("description", desc.trim());
    fd.set("file", file);
    const d = await run(() => api.upload(caseId, fd));
    if (d) {
      setTitle(""); setDesc(""); setType("auto");
      if (fileRef.current) fileRef.current.value = "";
      onUploaded(d);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>File a document</h2>
      <p className="muted small" style={{ marginTop: -6 }}>
        The file is hashed, OCR'd/classified locally, encrypted, and its SHA-256 is anchored on the integrity ledger.
        Allowed: PDF, TXT, PNG, JPG, TIFF, DOCX.
      </p>
      <Msg error={error} ok={ok && "Document filed and anchored."} />
      <div className="row">
        <div><label htmlFor="dt">Title</label><input id="dt" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} /></div>
        <div>
          <label htmlFor="dtype">Document type</label>
          <select id="dtype" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="auto">Auto-detect (AI)</option>
            {DOC_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select>
        </div>
        <div><label htmlFor="file">File</label><input id="file" ref={fileRef} type="file" required accept=".pdf,.txt,.png,.jpg,.jpeg,.tif,.tiff,.docx" /></div>
      </div>
      <div className="field"><label htmlFor="dd">Description (optional)</label><input id="dd" value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={4000} /></div>
      <button className="btn" disabled={busy}>{busy ? "Filing…" : "Upload"}</button>
    </form>
  );
}

function Assignees({ c, officers, onChange }: { c: CaseT; officers: User[]; onChange: (c: CaseT) => void }) {
  const [pick, setPick] = useState("");
  const { busy, error, run } = useAction();
  const free = officers.filter((o) => o.is_active && !c.assignees.some((a) => a.user_id === o.id));
  return (
    <div>
      <Msg error={error} />
      <div className="chips" style={{ marginBottom: 10 }}>
        {c.assignees.length === 0 && <Badge kind="warn">No officer assigned</Badge>}
        {c.assignees.map((a) => (
          <span className="chip" key={a.user_id}>
            {a.full_name} ({a.username}){" "}
            <button className="btn secondary small" disabled={busy} onClick={async () => { const r = await run(() => api.unassign(c.id, a.user_id)); if (r) onChange(r); }}>✕</button>
          </span>
        ))}
      </div>
      <div className="actions">
        <select aria-label="Officer to assign" value={pick} onChange={(e) => setPick(e.target.value)} style={{ maxWidth: 280 }}>
          <option value="">Assign an officer…</option>
          {free.map((o) => <option key={o.id} value={o.id}>{o.full_name} ({o.username})</option>)}
        </select>
        <button className="btn small" disabled={!pick || busy} onClick={async () => { const r = await run(() => api.assign(c.id, Number(pick))); if (r) { onChange(r); setPick(""); } }}>Assign</button>
      </div>
    </div>
  );
}

function Shares({ c, reviewers, onChange }: { c: CaseT; reviewers: User[]; onChange: (c: CaseT) => void }) {
  const [pick, setPick] = useState("");
  const { busy, error, run } = useAction();
  const free = reviewers.filter((r) => r.is_active && !c.shares.some((s) => s.user_id === r.id));
  return (
    <div className="card">
      <h2>Shared with (forensic / judge)</h2>
      <p className="muted small" style={{ marginTop: -6 }}>
        Read-only access to this case's documents: view, download, verify. No upload, no editing. No expiry yet — remove access manually when the review is done.
      </p>
      <Msg error={error} />
      <div className="chips" style={{ marginBottom: 10 }}>
        {c.shares.length === 0 && <span className="muted small">Not shared with anyone.</span>}
        {c.shares.map((s) => (
          <span className="chip" key={s.user_id}>
            {s.full_name} ({s.username}, {s.role}){" "}
            <button className="btn secondary small" disabled={busy} onClick={async () => { const r = await run(() => api.unshare(c.id, s.user_id)); if (r) onChange(r); }}>✕</button>
          </span>
        ))}
      </div>
      <div className="actions">
        <select aria-label="Reviewer to share with" value={pick} onChange={(e) => setPick(e.target.value)} style={{ maxWidth: 280 }}>
          <option value="">Share with…</option>
          {free.map((r) => <option key={r.id} value={r.id}>{r.full_name} ({r.username}, {r.role})</option>)}
        </select>
        <button className="btn small" disabled={!pick || busy} onClick={async () => { const r = await run(() => api.share(c.id, Number(pick))); if (r) { onChange(r); setPick(""); } }}>Share</button>
      </div>
    </div>
  );
}

export default function CaseDetail() {
  const caseId = Number(useParams().id);
  const { user } = useAuth();
  const nav = useNavigate();
  const canSeeContent = hasContentAccess(user);
  const canUpload = canWrite(user);  // AI case-overview, assignments: full investigating-officer actions only
  const canFileDocument = canUpload || user?.role === "forensic";  // + a forensic lab filing its own findings
  const canManageShares = user?.role === "officer" || user?.role === "admin";
  const c = useLoad(() => api.case(caseId), [caseId]);
  const docs = useLoad(() => (canSeeContent ? api.documents(caseId) : Promise.resolve([] as DocumentT[])), [caseId, canSeeContent]);
  const officers = useLoad(() => (user?.role === "admin" ? api.users() : Promise.resolve([] as User[])), [user?.role]);
  const reviewers = useLoad(() => (canManageShares ? api.reviewers() : Promise.resolve([] as User[])), [canManageShares]);
  const [overview, setOverview] = useState<CaseSummary | null>(null);
  const summarise = useAction();

  if (c.loading || c.error || !c.data) return <Loading loading={c.loading} error={c.error} />;
  const cs = c.data;

  return (
    <>
      <div className="pagehead">
        <div>
          <div className="small"><Link to="/cases">← Cases</Link></div>
          <h1>{cs.title}</h1>
          <div className="muted mono">{cs.case_number}</div>
        </div>
        <Badge kind={cs.status === "open" ? "ok" : undefined}>{cs.status}</Badge>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Case details</h2>
          <dl className="kv">
            <dt>FIR number</dt><dd>{cs.fir_number ?? "—"}</dd>
            <dt>Type</dt><dd>{cs.case_type ?? "—"}</dd>
            <dt>Registered</dt><dd>{fmtTime(cs.created_at)}</dd>
            <dt>Description</dt><dd>{cs.description ?? "—"}</dd>
            <dt>Parties</dt>
            <dd>{cs.parties.length ? cs.parties.map((p) => <div key={p.name + p.role}>{p.name} <Badge>{p.role}</Badge></div>) : "—"}</dd>
          </dl>
        </div>
        <div className="card">
          <h2>Assigned officers</h2>
          {user?.role === "admin"
            ? <Assignees c={cs} officers={officers.data ?? []} onChange={(x) => c.setData(x)} />
            : <div className="chips">{cs.assignees.map((a) => <span className="chip" key={a.user_id}>{a.full_name} ({a.username})</span>)}</div>}
          {user?.role === "admin" && <p className="muted small" style={{ marginBottom: 0 }}>Station admins manage assignments but cannot open document content.</p>}
        </div>
      </div>

      {canManageShares && <Shares c={cs} reviewers={reviewers.data ?? []} onChange={(x) => c.setData(x)} />}

      {canSeeContent && (
        <>
          {canFileDocument && <UploadForm caseId={caseId} onUploaded={(d) => { void docs.reload(); void c.reload(); nav(`/documents/${d.id}`); }} />}
          {canUpload && (
            <div className="card">
              <div className="pagehead" style={{ marginBottom: 8 }}>
                <h2 style={{ margin: 0 }}>Case overview <span className="muted small">(written by the local AI model from the extracted text)</span></h2>
                <button className="btn secondary small" disabled={summarise.busy || !docs.data?.length}
                  onClick={async () => { const r = await summarise.run(() => api.summarizeCase(caseId)); if (r) setOverview(r); }}>
                  {summarise.busy ? "Summarising… this can take a minute" : overview ? "Regenerate" : "Summarise case"}
                </button>
              </div>
              <Msg error={summarise.error} />
              {overview && !overview.available && <Alert kind="warn">No reliable overview could be produced: the local AI model is unavailable, or everything it wrote contained details not found in the documents and was discarded.</Alert>}
              {overview?.available && (
                <>
                  <p style={{ marginTop: 0 }}>{overview.overall}</p>
                  <dl className="kv">
                    {Object.entries(overview.by_type).map(([t, s]) => <div key={t} style={{ display: "contents" }}><dt>{label(t)}</dt><dd>{s}</dd></div>)}
                  </dl>
                  <div className="muted small">Based on {overview.documents} document(s). AI-written text can be wrong — check the source documents.</div>
                </>
              )}
              {!overview && <div className="muted small">Generated on request; nothing is sent outside this machine.</div>}
            </div>
          )}
          <div className="card tablewrap">
            <h2>Documents</h2>
            <Loading loading={docs.loading} error={docs.error} />
            {docs.data && docs.data.length === 0 && <div className="muted">No documents filed yet.</div>}
            {docs.data && docs.data.length > 0 && (
              <table>
                <thead><tr><th>Title</th><th>Type</th><th>Ver.</th><th>SHA-256</th><th>Ledger tx</th><th>Filed</th></tr></thead>
                <tbody>
                  {docs.data.map((d) => {
                    const v = d.versions[d.versions.length - 1];
                    return (
                      <tr key={d.id} className="clickable" onClick={() => nav(`/documents/${d.id}`)}>
                        <td><Link to={`/documents/${d.id}`} onClick={(e) => e.stopPropagation()}>{d.title}</Link><div className="muted small">{v.filename} · {fmtSize(v.size)}</div></td>
                        <td>{label(d.doc_type)}</td>
                        <td>v{d.current_version}</td>
                        <td className="mono" title={v.sha256}>{shortHash(v.sha256)}</td>
                        <td className="mono" title={v.ledger_tx_id ?? ""}>{shortHash(v.ledger_tx_id)}</td>
                        <td>{fmtTime(v.uploaded_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </>
  );
}
