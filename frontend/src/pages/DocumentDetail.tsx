import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api, APPROVAL_LABEL, canEditDocument, canSeeCustody, canWrite, DOC_TYPES, fmtSize, fmtTime, isApprover, label, ROLE_LABEL, shortHash,
  type DiffT, type DocumentT, type Role, type SignatureT, type User, type VerifyT, type VersionT,
} from "../api";
import { useAuth } from "../auth";
import { EditHistory } from "../history";
import { Alert, Badge, Chips, Loading, Msg, useAction, useLoad } from "../ui";

function VerifyResult({ r }: { r: VerifyT }) {
  return r.status === "verified" ? (
    <Alert kind="ok">
      <strong>Verified.</strong> The stored file re-hashes to <span className="mono">{shortHash(r.recomputed_sha256, 16)}</span>, matching both the
      database record and the hash anchored on the ledger (block #{r.ledger_block}).
    </Alert>
  ) : (
    <Alert kind="err">
      <strong>Integrity check FAILED — possible tampering.</strong> This event has been written to the audit trail.
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
    </Alert>
  );
}

function Diff({ d }: { d: DiffT }) {
  if (!d.available) return <Alert kind="warn">{d.note}</Alert>;
  if (d.lines.length === 0) return <Alert kind="ok">The extracted text of version {d.to_version} is identical to version {d.from_version}.</Alert>;
  const cls = { "+": "add", "-": "del", "@": "hunk", " ": "" } as const;
  return (
    <>
      <div className="small" style={{ marginTop: 8 }}>
        Changes from version {d.from_version} to version {d.to_version}: <Badge kind="ok">{d.added} line(s) added</Badge> <Badge kind="err">{d.removed} line(s) removed</Badge>
        {d.truncated && <span className="muted"> · long diff, first part shown</span>}
      </div>
      <div className="diff" aria-label={`Changes in version ${d.to_version}`}>
        {d.lines.map((ln, i) => <div key={i} className={cls[ln.op]}>{ln.op === "@" ? ln.text : `${ln.op} ${ln.text}`}</div>)}
      </div>
    </>
  );
}

type Shown = { kind: "image" | "pdf" | "video" | "audio" | "text"; url?: string; text?: string; note?: string };

/** Shows a verified version in the page: images, PDFs, audio/video and text natively; DOCX/TIFF as their extracted text. */
function Viewer({ s }: { s: Shown }) {
  useEffect(() => () => { if (s.url) URL.revokeObjectURL(s.url); }, [s.url]);
  return (
    <div className="viewer">
      {s.note && <div className="small muted" style={{ padding: "6px 10px" }}>{s.note}</div>}
      {s.kind === "image" && <img src={s.url} alt="Document" />}
      {s.kind === "pdf" && <iframe src={s.url} title="Document" />}
      {s.kind === "video" && <video src={s.url} controls />}
      {s.kind === "audio" && <audio src={s.url} controls />}
      {s.kind === "text" && <pre>{s.text}</pre>}
    </div>
  );
}

async function show(docId: number, v: VersionT): Promise<Shown> {
  const t = v.content_type;
  if (t === "text/plain") return { kind: "text", text: await (await api.viewBlob(docId, v.version_no)).text() };
  const native = t.startsWith("image/") && t !== "image/tiff" ? "image" : t === "application/pdf" ? "pdf"
    : t.startsWith("video/") ? "video" : t.startsWith("audio/") ? "audio" : null;
  if (native) return { kind: native, url: URL.createObjectURL(await api.viewBlob(docId, v.version_no)) };
  const x = await api.extractedText(docId, v.version_no);  // DOCX, TIFF: the browser can't render them
  return { kind: "text", text: x.available ? x.text : "No text could be extracted from this file. Download it to open it.",
           note: `Showing the text extracted from ${v.filename}${x.method ? ` (${x.method.replace(/_/g, " ")})` : ""} — download the file for the original layout.` };
}

function Signatures({ docId, v, user }: { docId: number; v: VersionT; user: User | null }) {
  const s = useLoad(() => api.signatures(docId, v.version_no), [docId, v.version_no]);
  const [pw, setPw] = useState("");
  const [open, setOpen] = useState(false);
  const act = useAction();
  const list: SignatureT[] = s.data?.signatures ?? [];
  return (
    <>
      <dt>Signatures</dt>
      <dd>
        {s.loading && <span className="muted">checking…</span>}
        {s.data && list.length === 0 && <span className="muted">Not signed.</span>}
        {list.length > 0 && (
          <ul className="sigs">{list.map((x) => (
            <li key={x.signer}>
              <Badge kind={x.valid ? "ok" : "err"}>{x.valid ? "valid" : "INVALID"}</Badge>{" "}
              {x.signer_name} <span className="muted">({x.signer}, {ROLE_LABEL[x.signer_role as Role] ?? x.signer_role})</span> · {fmtTime(x.signed_at)}
              <span className="muted small"> · key {x.fingerprint}</span>
              {!x.valid && <div className="small" style={{ color: "var(--err)" }}>{x.problems.join("; ")}</div>}
            </li>
          ))}</ul>
        )}
        {s.data?.can_sign && !open && <button className="btn secondary small" style={{ marginTop: 6 }} onClick={() => setOpen(true)}>Sign this version</button>}
        {open && (
          <form className="actions" style={{ marginTop: 6 }} onSubmit={async (e) => {
            e.preventDefault();
            const r = await act.run(() => api.sign(docId, v.version_no, pw), "Signed. The signature covers this exact file (its SHA-256).");
            if (r) { setPw(""); setOpen(false); void s.reload(); }
          }}>
            <input type="password" aria-label="Your password" placeholder={`Password of ${user?.username}`} value={pw} onChange={(e) => setPw(e.target.value)} required style={{ maxWidth: 240 }} autoComplete="current-password" />
            <button className="btn small" disabled={act.busy || !pw}>{act.busy ? "Signing…" : "Sign"}</button>
            <button type="button" className="btn secondary small" onClick={() => { setOpen(false); setPw(""); }}>Cancel</button>
          </form>
        )}
        <Msg error={act.error ?? s.error} ok={act.ok} />
      </dd>
    </>
  );
}

function VersionCard({ docId, v, isCurrent, onChanged, aiActions, canRelabel, user }: { docId: number; v: VersionT; isCurrent: boolean; onChanged: () => void; aiActions: boolean; canRelabel: boolean; user: User | null }) {
  const [result, setResult] = useState<VerifyT | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);
  const view = useAction();
  const [summary, setSummary] = useState<string | null>(v.summary);
  const [newType, setNewType] = useState(v.ai_doc_type ?? "other");
  const [diff, setDiff] = useState<DiffT | null>(null);
  const verify = useAction();
  const dl = useAction();
  const sum = useAction();
  const fb = useAction();
  const df = useAction();
  const entities = Object.entries(v.ai_entities).filter(([, xs]) => xs.length);

  return (
    <div className="card">
      <div className="pagehead" style={{ marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Version {v.version_no} {isCurrent && <Badge kind="ok">current</Badge>}</h2>
        <div className="actions">
          {v.version_no > 1 && (
            <button className="btn secondary small" disabled={df.busy}
              onClick={async () => { if (diff) { setDiff(null); return; } const r = await df.run(() => api.versionDiff(docId, v.version_no)); if (r) setDiff(r); }}>
              {df.busy ? "Comparing…" : diff ? "Hide changes" : `Show changes from v${v.version_no - 1}`}
            </button>
          )}
          <button className="btn secondary small" disabled={view.busy}
            onClick={async () => { if (shown) { setShown(null); return; } const r = await view.run(() => show(docId, v)); if (r) setShown(r); }}>
            {view.busy ? "Checking & opening…" : shown ? "Close viewer" : "View"}
          </button>
          {canSeeCustody(user) && <Link className="btn secondary small" to={`/documents/${docId}/certificate/${v.version_no}`}>Section 63 certificate</Link>}
          <button className="btn secondary small" disabled={verify.busy} onClick={async () => setResult((await verify.run(() => api.verify(docId, v.version_no))) ?? null)}>
            {verify.busy ? "Verifying…" : "Verify integrity"}
          </button>
          <button className="btn small" disabled={dl.busy} onClick={() => dl.run(() => api.download(docId, v.version_no, v.filename))}>
            {dl.busy ? "Checking & downloading…" : "Download"}
          </button>
        </div>
      </div>
      <Msg error={verify.error ?? dl.error ?? df.error ?? view.error} />
      {result && <VerifyResult r={result} />}
      {shown && <Viewer s={shown} />}
      {diff && <div style={{ marginBottom: 12 }}><Diff d={diff} /></div>}
      <dl className="kv">
        <dt>File</dt><dd>{v.filename} <span className="muted">({v.content_type}, {fmtSize(v.size)})</span></dd>
        <dt>{v.version_no > 1 ? "Edited by" : "Filed by"}</dt><dd>{v.uploaded_by} · {fmtTime(v.uploaded_at)}</dd>
        {v.change_note && <><dt>Reason for edit</dt><dd>{v.change_note}</dd></>}
        <dt>SHA-256</dt><dd className="mono hash">{v.sha256}</dd>
        <Signatures docId={docId} v={v} user={user} />
        <dt>Ledger tx</dt><dd className="mono hash">{v.ledger_tx_id ?? "—"} {v.ledger_block != null && <span className="muted">(block #{v.ledger_block})</span>}</dd>
        <dt>Text extraction</dt>
        <dd>
          {v.ocr_method ? `${v.ocr_method.replace(/_/g, " ")}` : "—"}
          {v.language && <span className="muted"> · language {v.language}</span>}
          {v.ocr_confidence ? <span className="muted"> · {(v.ocr_confidence * 100).toFixed(0)}% confidence</span> : null}{" "}
          {v.needs_review && <Badge kind="warn">needs human review</Badge>}
        </dd>
        <dt>AI suggestion</dt>
        <dd>
          {v.ai_doc_type ? label(v.ai_doc_type) : "—"}
          {v.ai_confidence ? <span className="muted"> · {(v.ai_confidence * 100).toFixed(0)}% confidence</span> : null}
          <span className="muted"> · engine: {v.ai_provider ?? "—"}</span>
          {canRelabel && (
            <div className="actions" style={{ marginTop: 6 }}>
              <select aria-label="Correct document type" value={newType} onChange={(e) => setNewType(e.target.value)} style={{ maxWidth: 220 }}>
                {DOC_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
              </select>
              <button className="btn secondary small" disabled={fb.busy}
                onClick={async () => { let done = false; await fb.run(async () => { await api.classificationFeedback(docId, newType); done = true; }, "Type updated and recorded in the edit history. The correction is kept (without any text) to improve the classifier."); if (done) onChanged(); }}>
                Set type
              </button>
            </div>
          )}
          <Msg error={fb.error} ok={fb.ok} />
        </dd>
        <dt>Summary</dt>
        <dd>
          {summary ? <p style={{ margin: "0 0 6px" }}>{summary}</p> : <span className="muted">Not generated yet. </span>}
          {summary && <div className="muted small" style={{ marginBottom: 6 }}>Written by the local AI model. Any sentence naming a section, date, amount or identifier that is not in the document is removed automatically — but check the source before relying on it.</div>}
          {aiActions && (
            <button className="btn secondary small" disabled={sum.busy}
              onClick={async () => { const r = await sum.run(() => api.summarizeVersion(docId, v.version_no)); if (r?.summary) setSummary(r.summary); else if (r && !r.available) sum.run(async () => { throw new Error("No reliable summary could be produced: the local AI model is unavailable, or everything it wrote contained details not found in the document and was discarded."); }); }}>
              {sum.busy ? "Summarising (local model)…" : summary ? "Regenerate" : "Summarise with local AI"}
            </button>
          )}
          <Msg error={sum.error} />
        </dd>
        <dt>Tags</dt><dd><Chips items={v.ai_tags} /></dd>
        {entities.map(([k, xs]) => (
          <div key={k} style={{ display: "contents" }}><dt>{label(k)}</dt><dd><Chips items={xs} /></dd></div>
        ))}
      </dl>
    </div>
  );
}

/** Edit panel: details (title/description), the text itself (text files), or a replacement file. Every path needs a reason. */
function EditPanel({ d, onSaved }: { d: DocumentT; onSaved: (d: DocumentT) => void }) {
  const current = d.versions[d.versions.length - 1];
  const isText = current.content_type === "text/plain";
  const [mode, setMode] = useState<"none" | "details" | "text" | "file">("none");
  const [title, setTitle] = useState(d.title);
  const [desc, setDesc] = useState(d.description ?? "");
  const [text, setText] = useState("");
  const [original, setOriginal] = useState("");
  const [reason, setReason] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const act = useAction();
  const reasonOk = reason.trim().length >= 3;

  function open(m: typeof mode) { act.clear(); setReason(""); setTitle(d.title); setDesc(d.description ?? ""); setMode(m); }

  async function openText() {
    open("none");
    const t = await act.run(() => api.versionText(d.id, current.version_no));
    if (t !== undefined) { setText(t); setOriginal(t); setMode("text"); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    let r: DocumentT | undefined;
    if (mode === "details") {
      r = await act.run(() => api.editDocument(d.id, { title: title.trim(), description: desc.trim(), reason: reason.trim() }), "Details updated. The change is recorded in the edit history.");
    } else {
      const fd = new FormData();
      fd.set("change_note", reason.trim());
      if (mode === "text") fd.set("file", new File([text], current.filename, { type: "text/plain" }));
      else {
        const file = fileRef.current?.files?.[0];
        if (!file) return;
        fd.set("file", file);
      }
      r = await act.run(() => api.uploadVersion(d.id, fd), (x) => `Saved as version ${x.current_version} and anchored on the ledger. Earlier versions are retained unchanged.`);
    }
    if (r) { onSaved(r); setMode("none"); setReason(""); }
  }

  const reasonField = (
    <div className="field">
      <label htmlFor="rsn">Reason for the edit (required)</label>
      <input id="rsn" value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={255} placeholder="What changed and why" />
    </div>
  );

  return (
    <div className="card">
      <div className="pagehead" style={{ marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Edit this document</h2>
        <div className="actions">
          <button type="button" className="btn secondary small" onClick={() => open("details")}>Edit title / description</button>
          {isText && <button type="button" className="btn secondary small" disabled={act.busy && mode === "none"} onClick={openText}>Edit text</button>}
          <button type="button" className="btn secondary small" onClick={() => open("file")}>Upload corrected file</button>
        </div>
      </div>
      <p className="muted small" style={{ marginTop: -6 }}>
        Edits never overwrite. A change to the file becomes a new hash-anchored version and the earlier ones stay; every
        edit is recorded with its date and time, your name and the reason, and is visible to the judge.
      </p>
      <Msg error={act.error} ok={act.ok} />
      {mode !== "none" && (
        <form onSubmit={submit}>
          {mode === "details" && (
            <>
              <div className="field"><label htmlFor="dti">Title</label><input id="dti" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} /></div>
              <div className="field"><label htmlFor="dde">Description</label><textarea id="dde" rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={4000} /></div>
            </>
          )}
          {mode === "text" && (
            <div className="field">
              <label htmlFor="dtx">Text of version {current.version_no} ({current.filename}) — saving creates version {current.version_no + 1}</label>
              <textarea id="dtx" className="doctext" rows={18} value={text} onChange={(e) => setText(e.target.value)} />
            </div>
          )}
          {mode === "file" && (
            <div className="field"><label htmlFor="vf">Corrected file</label><input id="vf" ref={fileRef} type="file" required accept=".pdf,.txt,.png,.jpg,.jpeg,.tif,.tiff,.docx,.mp4,.mov,.webm,.mkv,.avi,.mp3,.wav,.m4a" /></div>
          )}
          {reasonField}
          <div className="actions">
            <button className="btn" disabled={act.busy || !reasonOk || (mode === "text" && (text === original || !text.trim()))}>
              {act.busy ? "Saving…" : mode === "details" ? "Save changes" : "Save as new version"}
            </button>
            <button type="button" className="btn secondary" onClick={() => setMode("none")}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}

function ApprovalPanel({ d, user, onDone }: { d: DocumentT; user: User | null; onDone: (d: DocumentT) => void }) {
  const [note, setNote] = useState("");
  const act = useAction();
  const decide = async (decision: "approve" | "return") => {
    const r = await act.run(() => api.decide(d.id, decision, note.trim() || undefined));
    if (r) { setNote(""); onDone(r); }
  };
  const kind = d.approval_status === "approved" ? "ok" : d.approval_status === "returned" ? "err" : "warn";
  const mayDecide = d.approval_status === "pending" && isApprover(user) && d.created_by !== user?.username;
  return (
    <div className="card">
      <h2>Approval <Badge kind={kind}>{APPROVAL_LABEL[d.approval_status]}</Badge></h2>
      {d.approval_status === "pending" && <p className="muted small" style={{ marginTop: -6 }}>The station head must approve this {label(d.doc_type)} before the court, prosecutor or defence can see it.</p>}
      {d.approval_by && (
        <p style={{ margin: "0 0 8px" }}>
          {d.approval_status === "returned" ? "Returned" : "Approved"} by <strong>{d.approval_by}</strong>{d.approval_at && <> on {fmtTime(d.approval_at)}</>}
          {d.approved_version && d.approval_status === "approved" && <> (version {d.approved_version}{d.current_version > d.approved_version ? <> — <strong>edited after approval</strong>, see the history below</> : null})</>}
          {d.approval_note && <><br /><span className="muted">Note:</span> {d.approval_note}</>}
        </p>
      )}
      {mayDecide && (
        <div className="actions">
          <input aria-label="Note" placeholder="Note (required when returning)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} style={{ maxWidth: 420 }} />
          <button className="btn small" disabled={act.busy} onClick={() => decide("approve")}>Approve</button>
          <button className="btn secondary small" disabled={act.busy || note.trim().length < 3} onClick={() => decide("return")}>Return for correction</button>
        </div>
      )}
      <Msg error={act.error} />
    </div>
  );
}

function Custody({ docId }: { docId: number }) {
  const c = useLoad(() => api.custody(docId), [docId]);
  const [all, setAll] = useState(false);
  const rows = c.data ?? [];
  const shownRows = all ? rows : rows.slice(-12);
  return (
    <div className="card tablewrap">
      <h2>Chain of custody</h2>
      <p className="muted small" style={{ marginTop: -6 }}>Everything that has happened to this document — filing, every view and download, verification, edits, signatures
        and refused attempts — straight from the hash-chained audit log.</p>
      <Loading loading={c.loading} error={c.error} />
      {rows.length > 0 && (
        <table className="compact">
          <thead><tr><th>Date and time</th><th>Who</th><th>What</th><th>Version</th></tr></thead>
          <tbody>{shownRows.map((e) => (
            <tr key={e.id}>
              <td style={{ whiteSpace: "nowrap" }}>{fmtTime(e.ts)}</td>
              <td>{e.actor ?? "—"} <span className="muted">{e.actor_role ? ROLE_LABEL[e.actor_role as Role] ?? e.actor_role : ""}</span></td>
              <td>{e.outcome === "denied" || e.outcome === "alert" || e.outcome === "failure" ? <strong style={{ color: "var(--err)" }}>{e.label}</strong> : e.label}</td>
              <td>{e.version_no ?? ""}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {rows.length > 12 && <button className="btn secondary small" style={{ marginTop: 8 }} onClick={() => setAll((x) => !x)}>{all ? "Show the latest only" : `Show all ${rows.length} entries`}</button>}
    </div>
  );
}

export default function DocumentDetail() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const doc = useLoad(() => api.document(id), [id]);
  const history = useLoad(() => api.documentHistory(id), [id]);

  if (doc.loading || doc.error || !doc.data) return <Loading loading={doc.loading} error={doc.error} />;
  const d = doc.data;
  const editable = canEditDocument(user, d);

  return (
    <>
      <div className="pagehead">
        <div>
          <div className="small"><Link to={`/cases/${d.case_id}`}>← Case {d.case_number}</Link></div>
          <h1>{d.title}</h1>
          <div className="muted">{label(d.doc_type)} · filed {fmtTime(d.created_at)}{d.created_by && ` by ${d.created_by} (${d.created_by_role})`}</div>
          {d.description && <div style={{ marginTop: 4 }}>{d.description}</div>}
        </div>
      </div>

      {editable ? (
        <EditPanel d={d} onSaved={(x) => { doc.setData(x); void history.reload(); }} />
      ) : (
        <div className="card"><span className="muted small">
          {d.case_status !== "open"
            ? "This case is closed: its documents can be viewed, downloaded and verified, but no longer edited."
            : d.created_by_role === "judge"
              ? "A recorded verdict is final and cannot be edited."
              : "You can view, download and verify this document. Only the department that filed it can edit it; any edit appears in the history below."}
        </span></div>
      )}

      {d.approval_status !== "not_required" && <ApprovalPanel d={d} user={user} onDone={(x) => { doc.setData(x); void history.reload(); }} />}

      {[...d.versions].reverse().map((v) => <VersionCard key={v.version_no} docId={d.id} v={v} isCurrent={v.version_no === d.current_version} onChanged={() => { void doc.reload(); void history.reload(); }} aiActions={canWrite(user)} canRelabel={editable && canWrite(user)} user={user} />)}

      <EditHistory items={history.data} loading={history.loading} error={history.error} showDocument={false} />
      {canSeeCustody(user) && <Custody docId={d.id} />}
    </>
  );
}
