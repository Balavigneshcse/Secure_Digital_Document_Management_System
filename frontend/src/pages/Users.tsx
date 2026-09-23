import { useState, type FormEvent } from "react";
import { api, type Rank } from "../api";
import { Badge, Loading, Msg, useAction, useLoad } from "../ui";

const RANK_LABEL: Record<Rank, string> = { officer: "Officer", station_head: "Station head (sees all station cases)", superintendent: "Superintendent" };

export default function UsersPage() {
  const users = useLoad(() => api.users(), []);
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const create = useAction();
  const act = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const u = await create.run(
      () => api.createUser({ username: username.trim(), full_name: fullName.trim(), password }),
      "Officer created. They must set their own password and enrol an authenticator at first sign-in.",
    );
    if (u) {
      setUsername(""); setFullName(""); setPassword("");
      void users.reload();
    }
  }

  return (
    <>
      <div className="pagehead">
        <div><h1>Officers</h1><div className="muted">Manage officer accounts in your station.</div></div>
      </div>

      <form className="card" onSubmit={submit}>
        <h2>Create officer account</h2>
        <Msg error={create.error} ok={create.ok} />
        <div className="row">
          <div><label htmlFor="un">Username</label><input id="un" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} pattern="[a-zA-Z0-9._\-]+" title="Letters, digits, dot, dash, underscore" autoComplete="off" /></div>
          <div><label htmlFor="fn">Full name</label><input id="fn" value={fullName} onChange={(e) => setFullName(e.target.value)} required /></div>
          <div><label htmlFor="pw">Temporary password</label><input id="pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={10} autoComplete="new-password" /></div>
          <div><button className="btn" disabled={create.busy}>{create.busy ? "Creating…" : "Create"}</button></div>
        </div>
      </form>

      <div className="card tablewrap">
        <Msg error={act.error} ok={act.ok} />
        <Loading loading={users.loading} error={users.error} />
        {users.data && users.data.length === 0 && <div className="muted">No officers yet.</div>}
        {users.data && users.data.length > 0 && (
          <table>
            <thead><tr><th>Username</th><th>Name</th><th>Rank</th><th>Status</th><th>MFA</th><th>Actions</th></tr></thead>
            <tbody>
              {users.data.map((u) => (
                <tr key={u.id}>
                  <td className="mono">{u.username}</td>
                  <td>{u.full_name}</td>
                  <td>
                    <select aria-label={`Rank for ${u.username}`} value={u.rank} disabled={act.busy}
                      onChange={async (e) => {
                        const rank = e.target.value as Rank;
                        await act.run(() => api.setActive(u.id, u.is_active, rank), `${u.username} is now ${RANK_LABEL[rank].toLowerCase()}.`);
                        void users.reload();
                      }}>
                      {(["officer", "station_head"] as const).map((r) => <option key={r} value={r}>{RANK_LABEL[r]}</option>)}
                    </select>
                  </td>
                  <td>
                    {u.is_active ? <Badge kind="ok">active</Badge> : <Badge kind="err">disabled</Badge>}{" "}
                    {u.must_change_password && <Badge kind="warn">temp password</Badge>}
                  </td>
                  <td>{u.totp_enabled ? <Badge kind="ok">enrolled</Badge> : <Badge kind="warn">not enrolled</Badge>}</td>
                  <td>
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
                    </div>
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
