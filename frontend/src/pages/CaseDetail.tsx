import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, APPROVAL_LABEL, canDecide, canFile, canWrite, DOC_TYPES, fmtSize, fmtTime, hasContentAccess, label, ROLE_LABEL, shortHash, STAGE_LABEL, type CaseSummary, type CaseT, type DocumentT, type Party, type Role, type User } from "../api";
import { useAuth } from "../auth";
import { EditHistory } from "../history";
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
        Allowed: PDF, TXT, PNG, JPG, TIFF, DOCX (up to 25 MB), and audio/video evidence such as CCTV clips — MP4, MOV,
        WEBM, MKV, AVI, MP3, WAV, M4A (up to 200 MB; stored and verified, not analysed by the AI).
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
        <div><label htmlFor="file">File</label><input id="file" ref={fileRef} type="file" required accept=".pdf,.txt,.png,.jpg,.jpeg,.tif,.tiff,.docx,.mp4,.mov,.webm,.mkv,.avi,.mp3,.wav,.m4a" /></div>
      </div>
      <div className="field"><label htmlFor="dd">Description (optional)</label><input id="dd" value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={4000} /></div>
      <button className="btn" disabled={busy}>{busy ? "Filing…" : "Upload"}</button>
    </form>
  );
}

const OUTCOMES: [string, string][] = [
  ["convicted", "Convicted"], ["acquitted", "Acquitted"], ["discharged", "Discharged"],
  ["dismissed", "Case dismissed"], ["disposed", "Disposed of"],
];

function VerdictForm({ caseId, onRecorded }: { caseId: number; onRecorded: (d: DocumentT) => void }) {
  const [outcome, setOutcome] = useState("convicted");
  const [sentence, setSentence] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [confirm, setConfirm] = useState(false);
  const { busy, error, run } = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const d = await run(() => api.verdict(caseId, { outcome, reasoning: reasoning.trim(), sentence: sentence.trim() || undefined }));
    if (d) onRecorded(d);
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>Record verdict</h2>
      <p className="muted small" style={{ marginTop: -6 }}>
        The judgment is filed as a document: hashed, encrypted and anchored on the integrity ledger, so any later change is detected.
        It is final — it cannot be edited or replaced, and the case is closed.
      </p>
      <Msg error={error} />
      <div className="row">
        <div>
          <label htmlFor="vo">Verdict</label>
          <select id="vo" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            {OUTCOMES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div><label htmlFor="vs">Sentence / order (optional)</label><input id="vs" value={sentence} onChange={(e) => setSentence(e.target.value)} maxLength={500} /></div>
      </div>
      <div className="field">
        <label htmlFor="vr">Reasons for the judgment</label>
        <textarea id="vr" rows={6} value={reasoning} onChange={(e) => setReasoning(e.target.value)} required minLength={20} maxLength={8000} />
      </div>
      <div className="field">
        <label><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} style={{ width: "auto", marginRight: 8 }} />
          I confirm this is the final judgment in this case.</label>
      </div>
      <button className="btn" disabled={busy || !confirm || reasoning.trim().length < 20}>{busy ? "Recording…" : "Record verdict"}</button>
    </form>
  );
}

const PARTY_ROLES = ["complainant", "accused", "witness", "victim", "other"] as const;

function EditCaseForm({ c, onSaved, onCancel }: { c: CaseT; onSaved: (c: CaseT) => void; onCancel: () => void }) {
  const [title, setTitle] = useState(c.title);
  const [fir, setFir] = useState(c.fir_number ?? "");
  const [type, setType] = useState(c.case_type ?? "");
  const [desc, setDesc] = useState(c.description ?? "");
  const [parties, setParties] = useState<Party[]>(c.parties);
  const [stage, setStage] = useState(c.stage);
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  const setParty = (i: number, patch: Partial<Party>) => setParties((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = await run(() => api.editCase(c.id, {
      title: title.trim(), fir_number: fir.trim(), case_type: type.trim(), description: desc.trim(),
      parties: parties.filter((p) => p.name.trim()), reason: reason.trim(), ...(stage !== c.stage ? { stage } : {}),
    }));
    if (r) onSaved(r);
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>Edit case details</h2>
      <p className="muted small" style={{ marginTop: -6 }}>
        Nothing is lost: the old and new value of every field you change, your name, the reason and the date and time
        are recorded in the edit history below, which judges and everyone else with access to this case can read.
      </p>
      <Msg error={error} />
      <div className="row">
        <div><label htmlFor="et">Title</label><input id="et" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} /></div>
        <div><label htmlFor="ef">FIR number</label><input id="ef" value={fir} onChange={(e) => setFir(e.target.value)} maxLength={64} /></div>
        <div><label htmlFor="ect">Case type</label><input id="ect" value={type} onChange={(e) => setType(e.target.value)} maxLength={64} /></div>
        <div><label htmlFor="estg">Stage</label>
          <select id="estg" value={stage} onChange={(e) => setStage(e.target.value)}>
            {["under_investigation", "charge_sheeted", "in_trial"].map((s) => <option key={s} value={s}>{STAGE_LABEL[s]}</option>)}
          </select></div>
      </div>
      <div className="field"><label htmlFor="ed">Description</label><textarea id="ed" rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={4000} /></div>
      <h3>Involved parties</h3>
      {parties.map((p, i) => (
        <div className="row" key={i} style={{ gridTemplateColumns: "2fr 1fr auto" }}>
          <input aria-label="Party name" placeholder="Name" value={p.name} onChange={(e) => setParty(i, { name: e.target.value })} maxLength={120} />
          <select aria-label="Party role" value={p.role} onChange={(e) => setParty(i, { role: e.target.value })}>
            {PARTY_ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
          <button type="button" className="btn secondary small" onClick={() => setParties((ps) => ps.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <div className="field"><button type="button" className="btn secondary small" onClick={() => setParties((ps) => [...ps, { name: "", role: "complainant" }])}>+ Add party</button></div>
      <div className="field">
        <label htmlFor="er">Reason for the edit (required)</label>
        <input id="er" value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} placeholder="What is being corrected and why" />
      </div>
      <div className="actions">
        <button className="btn" disabled={busy || reason.trim().length < 3}>{busy ? "Saving…" : "Save changes"}</button>
        <button type="button" className="btn secondary" onClick={onCancel}>Cancel</button>
      </div>
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

function ReopenCard({ c, onDone }: { c: CaseT; onDone: (c: CaseT) => void }) {
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  return (
    <div className="card">
      <h2>Reopen this case</h2>
      <p className="muted small" style={{ marginTop: -6 }}>For a review, an appeal or fresh evidence. The judgment already on file stays unchanged; the
        case can be added to again and a further verdict recorded. The reopening and its reason go into the edit history.</p>
      <Msg error={error} />
      <div className="actions">
        <input aria-label="Reason for reopening" placeholder="Reason for reopening" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} style={{ maxWidth: 480 }} />
        <button className="btn" disabled={busy || reason.trim().length < 3}
          onClick={async () => { const r = await run(() => api.reopen(c.id, reason.trim())); if (r) { onDone(r); setReason(""); } }}>Reopen case</button>
      </div>
    </div>
  );
}

function Shares({ c, reviewers, onChange }: { c: CaseT; reviewers: User[]; onChange: (c: CaseT) => void }) {
  const [pick, setPick] = useState("");
  const [days, setDays] = useState("30");
  const { busy, error, run } = useAction();
  const free = reviewers.filter((r) => r.is_active && !c.shares.some((s) => s.user_id === r.id && !s.expired));
  return (
    <div className="card">
      <h2>Shared with (forensic lab / judge / prosecutor / defence)</h2>
      <p className="muted small" style={{ marginTop: -6 }}>
        A judge and the prosecutor read the case's documents; a forensic lab files its own findings and sees only those; the
        defence sees the FIR, and the charge sheet and its supporting documents once the case is charge-sheeted. Access ends
        automatically after the period you choose.
      </p>
      <Msg error={error} />
      <div className="chips" style={{ marginBottom: 10 }}>
        {c.shares.length === 0 && <span className="muted small">Not shared with anyone.</span>}
        {c.shares.map((s) => (
          <span className={`chip ${s.expired ? "expired" : ""}`} key={s.user_id}>
            {s.full_name} ({s.username}, {ROLE_LABEL[s.role as Role] ?? s.role})
            {s.expired ? <> · <strong>expired</strong></> : s.expires_at ? <> · until {fmtTime(s.expires_at)}</> : <> · no end date</>}{" "}
            <button className="btn secondary small" disabled={busy} onClick={async () => { const r = await run(() => api.unshare(c.id, s.user_id)); if (r) onChange(r); }}>✕</button>
          </span>
        ))}
      </div>
      <div className="actions">
        <select aria-label="Reviewer to share with" value={pick} onChange={(e) => setPick(e.target.value)} style={{ maxWidth: 280 }}>
          <option value="">Share with…</option>
          {free.map((r) => <option key={r.id} value={r.id}>{r.full_name} ({r.username}, {ROLE_LABEL[r.role]})</option>)}
        </select>
        <select aria-label="Access period" value={days} onChange={(e) => setDays(e.target.value)} style={{ maxWidth: 160 }}>
          {[["7", "for 7 days"], ["30", "for 30 days"], ["90", "for 90 days"], ["365", "for 1 year"], ["", "until removed"]].map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
        <button className="btn small" disabled={!pick || busy} onClick={async () => { const r = await run(() => api.share(c.id, Number(pick), days ? Number(days) : undefined)); if (r) { onChange(r); setPick(""); } }}>Share</button>
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
  const canFileDocument = canFile(user);  // officers, + forensic/prosecutor/defence filing their own documents
  const canManageShares = user?.role === "officer" || user?.role === "admin";
  const c = useLoad(() => api.case(caseId), [caseId]);
  const docs = useLoad(() => (canSeeContent ? api.documents(caseId) : Promise.resolve([] as DocumentT[])), [caseId, canSeeContent]);
  const officers = useLoad(() => (user?.role === "admin" ? api.users() : Promise.resolve([] as User[])), [user?.role]);
  const reviewers = useLoad(() => (canManageShares ? api.reviewers() : Promise.resolve([] as User[])), [canManageShares]);
  const history = useLoad(() => api.caseHistory(caseId), [caseId]);
  const [editing, setEditing] = useState(false);
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
        <div className="actions">
          {cs.can_edit && !editing && <button className="btn secondary small" onClick={() => setEditing(true)}>Edit case details</button>}
          <Badge kind={cs.status === "open" ? "ok" : undefined}>{STAGE_LABEL[cs.stage] ?? cs.stage}</Badge>
          {cs.status !== "open" && <Badge>closed</Badge>}
        </div>
      </div>

      {editing && <EditCaseForm c={cs} onCancel={() => setEditing(false)} onSaved={(x) => { c.setData(x); setEditing(false); void history.reload(); }} />}

      <div className="grid2">
        <div className="card">
          <h2>Case details</h2>
          <dl className="kv">
            <dt>FIR number</dt><dd>{cs.fir_number ?? "—"}</dd>
            <dt>Type</dt><dd>{cs.case_type ?? "—"}</dd>
            <dt>Station</dt><dd>{cs.station_name ?? "—"}</dd>
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

      {cs.can_reopen && <ReopenCard c={cs} onDone={(x) => { c.setData(x); void history.reload(); }} />}
      {canManageShares && <Shares c={cs} reviewers={reviewers.data ?? []} onChange={(x) => c.setData(x)} />}

      {canSeeContent && (
        <>
          {canFileDocument && cs.status === "open" && <UploadForm caseId={caseId} onUploaded={(d) => { void docs.reload(); void c.reload(); nav(`/documents/${d.id}`); }} />}
          {cs.status !== "open" && <div className="card muted small">This case is closed by a verdict: nothing can be filed or edited unless the court reopens it.</div>}
          {canDecide(user) && cs.status === "open" && (
            <VerdictForm caseId={caseId} onRecorded={(d) => { void docs.reload(); void c.reload(); nav(`/documents/${d.id}`); }} />
          )}
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
                <thead><tr><th>Title</th><th>Type</th><th>Ver.</th><th>Approval</th><th>SHA-256</th><th>Ledger tx</th><th>Filed</th></tr></thead>
                <tbody>
                  {docs.data.map((d) => {
                    const v = d.versions[d.versions.length - 1];
                    return (
                      <tr key={d.id} className="clickable" onClick={() => nav(`/documents/${d.id}`)}>
                        <td><Link to={`/documents/${d.id}`} onClick={(e) => e.stopPropagation()}>{d.title}</Link><div className="muted small">{v.filename} · {fmtSize(v.size)}</div></td>
                        <td>{label(d.doc_type)}</td>
                        <td>v{d.current_version}</td>
                        <td>{d.approval_status === "not_required" ? <span className="muted">—</span>
                          : <Badge kind={d.approval_status === "approved" ? "ok" : d.approval_status === "returned" ? "err" : "warn"}>{APPROVAL_LABEL[d.approval_status]}</Badge>}</td>
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

      <EditHistory items={history.data} loading={history.loading} error={history.error} showDocument />
    </>
  );
}
