import { Link, useParams } from "react-router-dom";
import { api, APPROVAL_LABEL, fmtSize, fmtTime, label, ROLE_LABEL, STAGE_LABEL, type Role } from "../api";
import { Loading, useLoad } from "../ui";

/** A printable certificate for one document version, laid out after the Section 63(4) Bharatiya Sakshya Adhiniyam
 *  form (Part A: the party producing the record; Part B: the expert). The system fills in the facts; the people named
 *  must still sign it by hand - the page says so. */
export default function CertificatePage() {
  const p = useParams();
  const id = Number(p.id), v = Number(p.v);
  const c = useLoad(() => api.certificate(id, v), [id, v]);
  if (c.loading || c.error || !c.data) return <Loading loading={c.loading} error={c.error} />;
  const x = c.data;

  return (
    <>
      <div className="actions noprint" style={{ marginBottom: 12 }}>
        <Link to={`/documents/${id}`}>← Back to the document</Link>
        <button className="btn" onClick={() => window.print()}>Print / save as PDF</button>
      </div>
      <article className="certificate">
        <header>
          <div className="small muted">Certificate no. <span className="mono">{x.certificate_no}</span></div>
          <h1>Certificate under Section 63(4)(c) of the Bharatiya Sakshya Adhiniyam, 2023</h1>
          <div className="muted">(corresponding to Section 65B(4) of the Indian Evidence Act, 1872) — in respect of an electronic record</div>
        </header>

        <section>
          <h2>Part A — the electronic record and how it was produced</h2>
          <p>
            I, <strong>{x.issued_by.name}</strong> ({ROLE_LABEL[x.issued_by.role as Role] ?? x.issued_by.role}
            {x.issued_by.station ? `, ${x.issued_by.station}` : ""}), state that the electronic record described below was
            produced from the {x.system.name} (SDMS), a computer system used regularly to store and manage the records of
            case <strong>{x.case.case_number}</strong>, and that throughout the period it was stored the system was operating
            properly.
          </p>
          <dl className="kv">
            <dt>Case</dt><dd>{x.case.case_number} — {x.case.title}{x.case.fir_number ? ` (FIR ${x.case.fir_number})` : ""}{x.case.station ? `, ${x.case.station}` : ""}</dd>
            <dt>Case stage</dt><dd>{STAGE_LABEL[x.case.stage] ?? x.case.stage} ({x.case.status})</dd>
            <dt>Record</dt><dd>{x.document.title} — {label(x.document.doc_type)}, version {x.document.version_no} of {x.document.versions}</dd>
            <dt>File</dt><dd>{x.document.filename} ({x.document.content_type}, {fmtSize(x.document.size)})</dd>
            <dt>Filed by</dt><dd>{x.document.uploaded_by} ({x.document.uploaded_by_username}) on {fmtTime(x.document.uploaded_at)}</dd>
            {x.document.change_note && <><dt>Reason for this version</dt><dd>{x.document.change_note}</dd></>}
            <dt>Approval</dt><dd>{APPROVAL_LABEL[x.approval.status] ?? x.approval.status}{x.approval.by ? ` by ${x.approval.by}` : ""}{x.approval.at ? ` on ${fmtTime(x.approval.at)}` : ""}{x.approval.version ? ` (version ${x.approval.version})` : ""}</dd>
          </dl>
        </section>

        <section>
          <h2>Integrity of the record</h2>
          <p>
            The file was hashed with {x.system.hash} when it was filed, stored encrypted ({x.system.encryption}), and its hash
            was recorded on {x.integrity.ledger}. When this certificate was generated ({fmtTime(x.integrity.checked_at)}) the
            stored file was decrypted and hashed again; the result matched both the database record and the ledger entry.
          </p>
          <dl className="kv">
            <dt>SHA-256 at filing</dt><dd className="mono hash">{x.integrity.sha256}</dd>
            <dt>SHA-256 now</dt><dd className="mono hash">{x.integrity.recomputed_sha256}</dd>
            <dt>SHA-256 on ledger</dt><dd className="mono hash">{x.integrity.ledger_sha256}</dd>
            <dt>Ledger transaction</dt><dd className="mono hash">{x.integrity.ledger_tx_id}{x.integrity.ledger_block != null ? ` (block #${x.integrity.ledger_block})` : ""}</dd>
            <dt>Result</dt><dd><strong>{x.integrity.status === "verified" ? "VERIFIED — unchanged since filing" : x.integrity.status}</strong></dd>
          </dl>
        </section>

        <section>
          <h2>Digital signatures on this version</h2>
          {x.signatures.length === 0 ? <p className="muted">None.</p> : (
            <ul>{x.signatures.map((s) => (
              <li key={s.signer}>{s.signer_name} ({s.signer}, {ROLE_LABEL[s.signer_role as Role] ?? s.signer_role}) — {fmtTime(s.signed_at)} —{" "}
                <strong>{s.valid ? "valid" : `INVALID: ${s.problems.join("; ")}`}</strong> <span className="muted small">key {s.fingerprint}</span></li>
            ))}</ul>
          )}
        </section>

        <section>
          <h2>Chain of custody</h2>
          <table className="compact">
            <thead><tr><th>Date and time</th><th>Who</th><th>What</th><th>Version</th></tr></thead>
            <tbody>{x.custody.map((e) => (
              <tr key={e.id}><td>{fmtTime(e.ts)}</td><td>{e.actor ?? "—"} <span className="muted">{e.actor_role ?? ""}</span></td>
                <td>{e.outcome === "denied" || e.outcome === "alert" ? <strong>{e.label}</strong> : e.label}</td><td>{e.version_no ?? ""}</td></tr>
            ))}</tbody>
          </table>
        </section>

        <section className="signlines">
          <div><div className="line" />Part A — {x.issued_by.name}<br /><span className="muted small">Signature, date, designation</span></div>
          <div><div className="line" />Part B — Expert<br /><span className="muted small">Name, signature, date, designation</span></div>
        </section>

        <footer className="small muted">
          Generated by SDMS on {fmtTime(x.issued_at)} by {x.issued_by.username}. Certificate fingerprint (SHA-256): <span className="mono hash">{x.certificate_sha256}</span>,
          recorded in the hash-chained audit log. This page is generated from the system's records; it takes effect as a
          certificate only when signed by the persons named in Part A and Part B.
        </footer>
      </article>
    </>
  );
}
