import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Msg, useAction } from "../ui";

export default function ChangePassword() {
  const { user, loading, startSession } = useAuth();
  const nav = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const { busy, error, run } = useAction();

  if (loading) return <div className="page spinner">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (next !== confirm) return void run(async () => { throw new Error("New passwords do not match"); });
    const r = await run(() => api.changePassword(current, next));
    if (r) {
      await startSession(r.token); // password change revokes the old session; continue on the new one
      nav("/", { replace: true });
    }
  }

  return (
    <div className="authwrap">
      <div className="authcard">
        <h1>{user.must_change_password ? "Set a new password" : "Change password"}</h1>
        {user.must_change_password && (
          <p className="muted" style={{ marginTop: 0 }}>Your account was issued with a temporary password. Choose your own before continuing.</p>
        )}
        <Msg error={error} />
        <form onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="cur">Current password</label>
            <input id="cur" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
          </div>
          <div className="field">
            <label htmlFor="new">New password</label>
            <input id="new" type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" minLength={10} required />
            <div className="small muted">At least 10 characters, with letters and digits, not containing your username.</div>
          </div>
          <div className="field">
            <label htmlFor="conf">Confirm new password</label>
            <input id="conf" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
          </div>
          <div className="actions">
            <button className="btn" disabled={busy}>{busy ? "Saving…" : "Update password"}</button>
            {!user.must_change_password && <Link to="/">Cancel</Link>}
          </div>
        </form>
      </div>
    </div>
  );
}
