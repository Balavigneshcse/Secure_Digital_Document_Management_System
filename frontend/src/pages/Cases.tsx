import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtTime, type Party } from "../api";
import { useAuth } from "../auth";
import { Badge, Loading, Msg, useAction, useLoad } from "../ui";

const PARTY_ROLES = ["complainant", "accused", "witness", "victim", "other"] as const;

function NewCaseForm({ isAdmin, onDone }: { isAdmin: boolean; onDone: (id: number) => void }) {
  const [title, setTitle] = useState("");
  const [fir, setFir] = useState("");
  const [type, setType] = useState("");
  const [desc, setDesc] = useState("");
  const [parties, setParties] = useState<Party[]>([]);
  const [officerIds, setOfficerIds] = useState<number[]>([]);
  const officers = useLoad(() => (isAdmin ? api.users() : Promise.resolve([])), [isAdmin]);
  const { busy, error, run } = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const c = await run(() =>
      api.createCase({
        title: title.trim(), fir_number: fir.trim() || undefined, case_type: type.trim() || undefined,
        description: desc.trim() || undefined, parties: parties.filter((p) => p.name.trim()),
        officer_ids: isAdmin ? officerIds : undefined,
      }),
    );
    if (c) onDone(c.id);
  }

  const setParty = (i: number, patch: Partial<Party>) => setParties((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  return (
    <form className="card" onSubmit={submit}>
      <h2>Register a new case</h2>
      <Msg error={error} />
      <div className="row">
        <div><label htmlFor="t">Title</label><input id="t" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} /></div>
        <div><label htmlFor="f">FIR number</label><input id="f" value={fir} onChange={(e) => setFir(e.target.value)} maxLength={64} /></div>
        <div><label htmlFor="ct">Case type</label><input id="ct" value={type} onChange={(e) => setType(e.target.value)} placeholder="e.g. theft, fraud" maxLength={64} /></div>
      </div>
      <div className="field"><label htmlFor="d">Description</label><textarea id="d" rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={4000} /></div>

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

      {isAdmin && (
        <div className="field">
          <h3>Assign officers</h3>
          {officers.data?.filter((o) => o.is_active).map((o) => (
            <label key={o.id} style={{ fontWeight: 400, color: "inherit" }}>
              <input type="checkbox" style={{ width: "auto", marginRight: 6 }} checked={officerIds.includes(o.id)}
                onChange={(e) => setOfficerIds((ids) => (e.target.checked ? [...ids, o.id] : ids.filter((x) => x !== o.id)))} />
              {o.full_name} <span className="muted">({o.username})</span>
            </label>
          ))}
          {officers.data?.length === 0 && <span className="muted">No officers in your station yet — create one under “Officers”.</span>}
        </div>
      )}
      <button className="btn" disabled={busy}>{busy ? "Creating…" : "Create case"}</button>
    </form>
  );
}

export default function CasesPage() {
  const { user } = useAuth();
  const nav = useNavigate();
  const { data, error, loading } = useLoad(() => api.cases(), []);
  const [showNew, setShowNew] = useState(false);
  const isAdmin = user?.role === "admin";
  const canCreate = user?.role === "officer" || isAdmin;
  const description = isAdmin
    ? "All cases in your station (metadata only — document content is restricted to assigned officers)"
    : user?.role === "forensic" || user?.role === "judge"
      ? "Cases shared with you for review"
      : user?.rank === "superintendent" ? "Cases assigned to you, and every case at the stations you oversee"
      : user?.rank === "station_head" ? "Cases assigned to you, and every case at your station"
      : "Cases assigned to you";

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Cases</h1>
          <div className="muted">{description}</div>
        </div>
        {canCreate && <button className="btn" onClick={() => setShowNew((s) => !s)}>{showNew ? "Close" : "+ New case"}</button>}
      </div>

      {showNew && canCreate && <NewCaseForm isAdmin={isAdmin} onDone={(id) => nav(`/cases/${id}`)} />}

      <div className="card tablewrap">
        <Loading loading={loading} error={error} />
        {data && data.length === 0 && <div className="muted">No cases yet.</div>}
        {data && data.length > 0 && (
          <table>
            <thead><tr><th>Case no.</th><th>Title</th><th>FIR</th><th>Type</th><th>Assigned</th><th>Docs</th><th>Registered</th></tr></thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => nav(`/cases/${c.id}`)}>
                  <td className="mono">{c.case_number}</td>
                  <td>{c.title}</td>
                  <td>{c.fir_number ?? "—"}</td>
                  <td>{c.case_type ?? "—"}</td>
                  <td>{c.assignees.map((a) => a.username).join(", ") || <Badge kind="warn">unassigned</Badge>}</td>
                  <td>{c.document_count ?? "—"}</td>
                  <td>{fmtTime(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
