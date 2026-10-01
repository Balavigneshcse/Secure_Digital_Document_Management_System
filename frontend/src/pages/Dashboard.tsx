import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api, fmtTime, label, ROLE_LABEL, STAGE_LABEL, type AlertT, type Role } from "../api";
import { useAuth } from "../auth";
import { Badge, Loading, useLoad } from "../ui";

function Tile({ n, text, to, kind }: { n: number | string; text: string; to?: string; kind?: "warn" | "err" }) {
  const body = <><div className={`tile-n ${kind ?? ""}`}>{n}</div><div className="tile-t">{text}</div></>;
  return to ? <Link className="tile" to={to}>{body}</Link> : <div className="tile">{body}</div>;
}

export function AlertList({ items }: { items: AlertT[] }) {
  if (items.length === 0) return <div className="muted">No alerts.</div>;
  return (
    <table>
      <thead><tr><th>When</th><th>Alert</th><th>Case / document</th><th>Detected by</th></tr></thead>
      <tbody>
        {items.map((a) => (
          <tr key={a.id}>
            <td style={{ whiteSpace: "nowrap" }}>{fmtTime(a.ts)} {a.unread && <Badge kind="err">new</Badge>}</td>
            <td><strong style={{ color: "var(--err)" }}>{a.label}</strong>{a.reasons.length > 0 && <div className="small muted">{a.reasons.join("; ")}</div>}</td>
            <td>
              {a.case_id ? <Link to={`/cases/${a.case_id}`}>{a.case_number}</Link> : (a.case_number ?? "—")}
              {a.document_id && <> · <Link to={`/documents/${a.document_id}`}>document {a.document_id}</Link></>}
            </td>
            <td>{a.actor ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const d = useLoad(() => api.dashboard(), []);
  // Opening the dashboard counts as having seen the alerts listed on it.
  useEffect(() => { if (d.data && d.data.alerts_unread > 0) void api.alertsSeen().then(() => window.dispatchEvent(new Event("sdms-alerts-seen"))); }, [d.data]);
  if (d.loading || d.error || !d.data || !user) return <Loading loading={d.loading} error={d.error} />;
  const x = d.data;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Welcome, {user.full_name}</h1>
          <div className="muted">{ROLE_LABEL[user.role as Role]}{user.station_name ? ` · ${user.station_name}` : ""}{user.district_name ? ` · ${user.district_name}` : ""}</div>
        </div>
      </div>

      <div className="tiles">
        {x.cases && <Tile n={x.cases.open} text="Open cases" to="/cases" />}
        {x.cases && <Tile n={x.cases.closed} text="Closed cases" to="/cases" />}
        {x.documents !== null && <Tile n={x.documents} text="Documents you can open" />}
        {x.approvals.length > 0 && <Tile n={x.approvals.length} text="Awaiting your approval" kind="warn" />}
        {x.returned.length > 0 && <Tile n={x.returned.length} text="Returned to you for correction" kind="warn" />}
        <Tile n={x.alerts_unread} text="New alerts" kind={x.alerts_unread ? "err" : undefined} />
      </div>

      {x.alerts.length > 0 && (
        <div className="card tablewrap" id="alerts">
          <h2>Alerts</h2>
          <p className="muted small" style={{ marginTop: -6 }}>Raised automatically when the system detects tampering or rejects a malicious upload in the cases you are responsible for.</p>
          <AlertList items={x.alerts} />
        </div>
      )}

      {x.approvals.length > 0 && (
        <div className="card tablewrap">
          <h2>Awaiting your approval</h2>
          <p className="muted small" style={{ marginTop: -6 }}>FIRs and charge sheets filed by officers of your station. The court cannot see them until you approve.</p>
          <table>
            <thead><tr><th>Document</th><th>Case</th><th>Filed by</th><th>Filed</th></tr></thead>
            <tbody>{x.approvals.map((a) => (
              <tr key={a.document_id}>
                <td><Link to={`/documents/${a.document_id}`}>{a.title}</Link> <span className="muted small">{label(a.doc_type)}</span></td>
                <td><Link to={`/cases/${a.case_id}`}>{a.case_number}</Link></td><td>{a.filed_by}</td><td>{fmtTime(a.filed_at)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {x.returned.length > 0 && (
        <div className="card tablewrap">
          <h2>Returned to you for correction</h2>
          <table>
            <thead><tr><th>Document</th><th>What to correct</th><th>Returned by</th></tr></thead>
            <tbody>{x.returned.map((r) => (
              <tr key={r.document_id}>
                <td><Link to={`/documents/${r.document_id}`}>{r.title}</Link></td><td>{r.note ?? "—"}</td>
                <td>{r.by ?? "—"}{r.at && <div className="muted small">{fmtTime(r.at)}</div>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {x.expiring_shares.length > 0 && (
        <div className="card tablewrap">
          <h2>Access ending within 7 days</h2>
          <table>
            <thead><tr><th>Case</th><th>Shared with</th><th>Ends</th></tr></thead>
            <tbody>{x.expiring_shares.map((s) => (
              <tr key={`${s.case_id}-${s.username}`}>
                <td><Link to={`/cases/${s.case_id}`}>{s.case_number}</Link></td><td>{s.username} <span className="muted small">{ROLE_LABEL[s.role as Role] ?? s.role}</span></td>
                <td>{fmtTime(s.expires_at)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {x.cases && (
        <div className="grid2">
          <div className="card">
            <h2>Cases by stage</h2>
            {Object.keys(x.cases.by_stage).length === 0 ? <div className="muted">No cases yet.</div> : (
              <dl className="kv">
                {Object.entries(x.cases.by_stage).map(([s, n]) => <div key={s} style={{ display: "contents" }}><dt>{STAGE_LABEL[s] ?? s}</dt><dd>{n}</dd></div>)}
              </dl>
            )}
          </div>
          <div className="card">
            <h2>Recent cases</h2>
            {(x.recent_cases ?? []).length === 0 ? <div className="muted">No cases yet.</div> : (
              <ul className="plain">
                {(x.recent_cases ?? []).map((c) => (
                  <li key={c.id}><Link to={`/cases/${c.id}`}>{c.title}</Link> <span className="muted small mono">{c.case_number}</span>{" "}
                    <Badge kind={c.status === "open" ? "ok" : undefined}>{STAGE_LABEL[c.stage] ?? c.stage}</Badge></li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
      {!x.cases && x.alerts.length === 0 && (
        <div className="card muted">
          {user.role === "auditor" ? <>Use the <Link to="/audit">Audit log</Link> and <Link to="/ledger">Integrity ledger</Link> to review activity.</>
            : <>Manage accounts under <Link to="/users">Users</Link>.</>}
        </div>
      )}
    </>
  );
}
