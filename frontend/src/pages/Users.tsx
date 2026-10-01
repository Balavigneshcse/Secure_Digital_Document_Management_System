import { useState, type FormEvent } from "react";
import { api, isSystemAdmin, ROLE_LABEL, type Org, type Rank, type Role, type User } from "../api";
import { useAuth } from "../auth";
import { Alert, Badge, Loading, Msg, useAction, useLoad } from "../ui";

const RANK_LABEL: Record<Rank, string> = {
  officer: "Officer", station_head: "Station head (sees all station cases, approves FIRs/charge sheets)", superintendent: "Superintendent",
  district_court: "District court judge", high_court: "High court judge", system: "System administrator",
};
// Ranks a system administrator may give each role (a station admin: officer / station head only).
const RANKS: Partial<Record<Role, Rank[]>> = {
  officer: ["officer", "station_head", "superintendent"], judge: ["officer", "district_court", "high_court"], admin: ["officer", "system"],
};
const rankText = (role: Role, rank: Rank) =>
  role === "judge" && rank === "officer" ? "Judge (shared cases only)" : role === "admin" && rank === "officer" ? "Station admin" : RANK_LABEL[rank];

function CreateForm({ system, org, onCreated }: { system: boolean; org: Org | null; onCreated: () => void }) {
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("officer");
  const [rank, setRank] = useState<Rank>("officer");
  const [station, setStation] = useState("");
  const [district, setDistrict] = useState("");
  const create = useAction();
  const ranks = RANKS[role] ?? ["officer"];
  const needsStation = (role === "officer" && rank !== "superintendent") || (role === "admin" && rank !== "system");
  const needsDistrict = role === "forensic" || (role === "judge" && rank === "district_court");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const u = await create.run(
      () => api.createUser({
        username: username.trim(), full_name: fullName.trim(), password,
        ...(system ? { role, rank, station_id: needsStation && station ? Number(station) : undefined, district_id: needsDistrict && district ? Number(district) : undefined } : {}),
      }),
      (x) => `${x.username} created. They must set their own password and enrol an authenticator at first sign-in.`,
    );
    if (u) { setUsername(""); setFullName(""); setPassword(""); onCreated(); }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>{system ? "Create an account" : "Create officer account"}</h2>
      <Msg error={create.error} ok={create.ok} />
      {system && (
        <div className="row">
          <div><label htmlFor="ur">Role</label>
            <select id="ur" value={role} onChange={(e) => { setRole(e.target.value as Role); setRank("officer"); }}>
              {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select></div>
          {ranks.length > 1 && <div><label htmlFor="uk">Rank</label>
            <select id="uk" value={rank} onChange={(e) => setRank(e.target.value as Rank)}>
              {ranks.map((r) => <option key={r} value={r}>{rankText(role, r)}</option>)}
            </select></div>}
          {needsStation && <div><label htmlFor="us">Station</label>
            <select id="us" value={station} onChange={(e) => setStation(e.target.value)} required>
              <option value="">Choose…</option>
              {org?.stations.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select></div>}
          {needsDistrict && <div><label htmlFor="ud">District</label>
            <select id="ud" value={district} onChange={(e) => setDistrict(e.target.value)} required>
              <option value="">Choose…</option>
              {org?.districts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select></div>}
        </div>
      )}
      <div className="row">
        <div><label htmlFor="un">Username</label><input id="un" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} pattern="[a-zA-Z0-9._\-]+" title="Letters, digits, dot, dash, underscore" autoComplete="off" /></div>
        <div><label htmlFor="fn">Full name</label><input id="fn" value={fullName} onChange={(e) => setFullName(e.target.value)} required /></div>
        <div><label htmlFor="pw">Temporary password</label><input id="pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={10} autoComplete="new-password" /></div>
        <div><button className="btn" disabled={create.busy}>{create.busy ? "Creating…" : "Create"}</button></div>
      </div>
      {system && role === "officer" && rank === "superintendent" && <div className="muted small">A superintendent's stations are granted with the operator CLI (<span className="mono">app.cli oversee</span>).</div>}
    </form>
  );
}

export default function UsersPage() {
  const { user } = useAuth();
  const system = isSystemAdmin(user);
  const users = useLoad(() => api.users(), []);
  const org = useLoad(() => (system ? api.org() : Promise.resolve(null)), [system]);
  const act = useAction();
  const [temp, setTemp] = useState<{ username: string; temporary_password: string } | null>(null);
  const [filter, setFilter] = useState<string>("");

  const rows = (users.data ?? []).filter((u) => !filter || u.role === filter);
  const rankOptions = (u: User): Rank[] => (system ? RANKS[u.role] ?? [] : ["officer", "station_head"]);

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>{system ? "Users" : "Officers"}</h1>
          <div className="muted">{system ? "Accounts of every role: police, forensic labs, courts, prosecutors, defence lawyers, auditors and admins." : "Manage officer accounts in your station."}</div>
        </div>
      </div>

      <CreateForm system={system} org={org.data} onCreated={() => void users.reload()} />

      <div className="card tablewrap">
        <Msg error={act.error} ok={act.ok} />
        {temp && (
          <Alert kind="warn">
            Temporary password for <strong>{temp.username}</strong>: <span className="mono">{temp.temporary_password}</span> — shown once only.
            Give it to them in person; they must change it at next sign-in, and still need their authenticator.{" "}
            <button className="btn secondary small" onClick={() => setTemp(null)}>Done</button>
          </Alert>
        )}
        {system && (
          <div className="actions" style={{ marginBottom: 10 }}>
            <select aria-label="Filter by role" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ maxWidth: 220 }}>
              <option value="">All roles</option>
              {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          </div>
        )}
        <Loading loading={users.loading} error={users.error} />
        {users.data && rows.length === 0 && <div className="muted">No accounts.</div>}
        {rows.length > 0 && (
          <table>
            <thead><tr><th>Username</th><th>Name</th>{system && <th>Role</th>}<th>Rank</th>{system && <th>Station / district</th>}<th>Status</th><th>MFA</th><th>Actions</th></tr></thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id}>
                  <td className="mono">{u.username}</td>
                  <td>{u.full_name}</td>
                  {system && <td>{ROLE_LABEL[u.role]}</td>}
                  <td>
                    {rankOptions(u).length > 1 && u.id !== user?.id ? (
                      <select aria-label={`Rank for ${u.username}`} value={u.rank} disabled={act.busy}
                        onChange={async (e) => {
                          const rank = e.target.value as Rank;
                          await act.run(() => api.setActive(u.id, u.is_active, rank), `${u.username}: ${rankText(u.role, rank)}.`);
                          void users.reload();
                        }}>
                        {rankOptions(u).map((r) => <option key={r} value={r}>{rankText(u.role, r)}</option>)}
                      </select>
                    ) : <span className="muted">{rankOptions(u).length > 1 ? rankText(u.role, u.rank) : "—"}</span>}
                  </td>
                  {system && <td>{u.station_name ?? u.district_name ?? "—"}</td>}
                  <td>
                    {u.is_active ? <Badge kind="ok">active</Badge> : <Badge kind="err">disabled</Badge>}{" "}
                    {u.must_change_password && <Badge kind="warn">temp password</Badge>}
                  </td>
                  <td>{u.totp_enabled ? <Badge kind="ok">enrolled</Badge> : <Badge kind="warn">not enrolled</Badge>}</td>
                  <td>
                    {u.id === user?.id ? <span className="muted small">you</span> : (
                      <div className="actions">
                        <button className="btn secondary small" disabled={act.busy}
                          onClick={async () => { await act.run(() => api.setActive(u.id, !u.is_active, u.rank), u.is_active ? `${u.username} disabled and signed out.` : `${u.username} re-enabled.`); void users.reload(); }}>
                          {u.is_active ? "Disable" : "Enable"}
                        </button>
                        <button className="btn secondary small" disabled={act.busy}
                          onClick={async () => { await act.run(() => api.unlock(u.id), `${u.username} unlocked.`); void users.reload(); }}>Unlock</button>
                        <button className="btn secondary small" disabled={act.busy}
                          onClick={async () => {
                            if (!window.confirm(`Reset MFA for ${u.username}? They will be signed out and must enrol a new authenticator.`)) return;
                            await act.run(() => api.resetMfa(u.id), `MFA reset for ${u.username}.`);
                            void users.reload();
                          }}>Reset MFA</button>
                        <button className="btn secondary small" disabled={act.busy}
                          onClick={async () => {
                            if (!window.confirm(`Reset the password of ${u.username}? They will be signed out everywhere.`)) return;
                            const r = await act.run(() => api.resetPassword(u.id));
                            if (r) { setTemp(r); void users.reload(); }
                          }}>Reset password</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
