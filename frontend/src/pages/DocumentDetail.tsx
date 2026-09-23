import { useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, canWrite, DOC_TYPES, fmtSize, fmtTime, label, shortHash, type VerifyT, type VersionT } from "../api";
import { useAuth } from "../auth";
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

function VersionCard({ docId, v, isCurrent, onChanged, editable }: { docId: number; v: VersionT; isCurrent: boolean; onChanged: () => void; editable: boolean }) {
  const [result, setResult] = useState<VerifyT | null>(null);
  const [summary, setSummary] = useState<string | null>(v.summary);
  const [newType, setNewType] = useState(v.ai_doc_type ?? "other");
  const verify = useAction();
  const dl = useAction();
  const sum = useAction();
  const fb = useAction();
  const entities = Object.entries(v.ai_entities).filter(([, xs]) => xs.length);

  return (
    <div className="card">
      <div className="pagehead" style={{ marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Version {v.version_no} {isCurrent && <Badge kind="ok">current</Badge>}</h2>
        <div className="actions">
          <button className="btn secondary small" disabled={verify.busy} onClick={async () => setResult((await verify.run(() => api.verify(docId, v.version_no))) ?? null)}>
            {verify.busy ? "Verifying…" : "Verify integrity"}
          </button>
          <button className="btn small" disabled={dl.busy} onClick={() => dl.run(() => api.download(docId, v.version_no, v.filename))}>
            {dl.busy ? "Checking & downloading…" : "Download"}
          </button>
        </div>
      </div>
      <Msg error={verify.error ?? dl.error} />
      {result && <VerifyResult r={result} />}
      <dl className="kv">
        <dt>File</dt><dd>{v.filename} <span className="muted">({v.content_type}, {fmtSize(v.size)})</span></dd>
        <dt>Filed by</dt><dd>{v.uploaded_by} · {fmtTime(v.uploaded_at)}</dd>
        {v.change_note && <><dt>Change note</dt><dd>{v.change_note}</dd></>}
        <dt>SHA-256</dt><dd className="mono hash">{v.sha256}</dd>
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
          {editable && (
            <div className="actions" style={{ marginTop: 6 }}>
              <select aria-label="Correct document type" value={newType} onChange={(e) => setNewType(e.target.value)} style={{ maxWidth: 220 }}>
                {DOC_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
              </select>
              <button className="btn secondary small" disabled={fb.busy}
                onClick={async () => { const r = await fb.run(() => api.classificationFeedback(docId, newType), "Type updated. The correction is kept (without any text) to improve the classifier."); if (r !== undefined) onChanged(); }}>
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
          {editable && (
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

export default function DocumentDetail() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const editable = canWrite(user);
  const doc = useLoad(() => api.document(id), [id]);
  const [note, setNote] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const up = useAction();

  if (doc.loading || doc.error || !doc.data) return <Loading loading={doc.loading} error={doc.error} />;
  const d = doc.data;

  async function addVersion(e: FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    const fd = new FormData();
    if (note.trim()) fd.set("change_note", note.trim());
    fd.set("file", file);
    const r = await up.run(() => api.uploadVersion(id, fd), "New version filed and anchored. Earlier versions are retained unchanged.");
    if (r) {
      doc.setData(r);
      setNote("");
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <div className="small"><Link to={`/cases/${d.case_id}`}>← Case {d.case_number}</Link></div>
          <h1>{d.title}</h1>
          <div className="muted">{label(d.doc_type)} · created {fmtTime(d.created_at)}</div>
          {d.description && <div style={{ marginTop: 4 }}>{d.description}</div>}
        </div>
      </div>

      {editable ? (
        <form className="card" onSubmit={addVersion}>
          <h2>Add a new version</h2>
          <p className="muted small" style={{ marginTop: -6 }}>Edits never overwrite: each upload becomes a new hash-anchored version and the full history stays available.</p>
          <Msg error={up.error} ok={up.ok} />
          <div className="row">
            <div><label htmlFor="vf">File</label><input id="vf" ref={fileRef} type="file" required accept=".pdf,.txt,.png,.jpg,.jpeg,.tif,.tiff,.docx" /></div>
            <div><label htmlFor="vn">Change note</label><input id="vn" value={note} onChange={(e) => setNote(e.target.value)} maxLength={255} placeholder="What changed and why" /></div>
            <div><button className="btn" disabled={up.busy}>{up.busy ? "Filing…" : "Upload version"}</button></div>
          </div>
        </form>
      ) : (
        <div className="card"><span className="muted small">Read-only access: shared with your account for review. You can view, download and verify, but not upload or change this document.</span></div>
      )}

      {[...d.versions].reverse().map((v) => <VersionCard key={v.version_no} docId={d.id} v={v} isCurrent={v.version_no === d.current_version} onChanged={() => void doc.reload()} editable={editable} />)}
    </>
  );
}
