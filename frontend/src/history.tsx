import { Link } from "react-router-dom";
import { fmtTime, type EditEntry } from "./api";
import { Badge, Loading } from "./ui";

/** 64-hex hashes are shortened for reading; the full value stays in the tooltip. */
const short = (v: string | null) => (v ?? "(empty)").replace(/\b([0-9a-f]{12})[0-9a-f]{52}\b/g, "$1…");

const KIND: Record<EditEntry["kind"], string> = { case: "Case details", document: "Document details", version: "New version", approval: "Approval" };

/** Every recorded edit: when (server time), who, what changed (old → new) and why. Read-only for everyone. */
export function EditHistory({ items, loading, error, showDocument }: { items: EditEntry[] | null; loading: boolean; error: string | null; showDocument: boolean }) {
  return (
    <div className="card tablewrap">
      <h2>Edit history</h2>
      <p className="muted small" style={{ marginTop: -6 }}>
        Every change is kept with its date and time, who made it, the old and new values and the reason. Each record is
        checked against the hash-chained audit log, so an edit cannot be hidden or rewritten afterwards.
      </p>
      <Loading loading={loading} error={error} />
      {items && items.length === 0 && <div className="muted">No edits have been made.</div>}
      {items && items.length > 0 && (
        <table className="history">
          <thead><tr><th>Date and time</th><th>Edited by</th><th>What was changed</th><th>Reason</th><th>Record</th></tr></thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id}>
                <td style={{ whiteSpace: "nowrap" }}>{fmtTime(e.ts)}</td>
                <td>{e.editor_name ?? e.editor ?? "—"}<div className="muted small">{e.editor} · {e.editor_role}</div></td>
                <td>
                  <div className="small" style={{ marginBottom: 4 }}>
                    <Badge>{KIND[e.kind]}{e.kind === "version" && e.version_no ? ` v${e.version_no}` : ""}</Badge>{" "}
                    {showDocument && e.document_id != null && <Link to={`/documents/${e.document_id}`}>{e.document_title ?? `Document ${e.document_id}`}</Link>}
                  </div>
                  {e.changes.map((c) => (
                    <div key={c.field} className="change">
                      <strong>{c.field}:</strong>{" "}
                      {c.old === null && c.new === null ? <span className="muted">values unavailable</span> : (
                        <><span className="old" title={c.old ?? ""}>{short(c.old)}</span> <span className="muted">→</span> <span className="new" title={c.new ?? ""}>{short(c.new)}</span></>
                      )}
                    </div>
                  ))}
                </td>
                <td>{e.reason ?? <span className="muted">—</span>}</td>
                <td>{e.verified ? <Badge kind="ok">verified</Badge> : <><Badge kind="err">TAMPERED</Badge><div className="small" style={{ color: "var(--err)" }}>{e.problem}</div></>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
