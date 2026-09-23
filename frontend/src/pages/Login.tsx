import { useState, type FormEvent } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Msg, useAction } from "../ui";

type Step =
  | { kind: "creds" }
  | { kind: "mfa"; token: string }
  | { kind: "setup"; token: string; secret: string; uri: string };

export default function Login() {
  const { user, startSession } = useAuth();
  const [step, setStep] = useState<Step>({ kind: "creds" });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const { busy, error, run, clear } = useAction();

  if (user) {
    return <Navigate to={user.must_change_password ? "/change-password" : user.role === "auditor" ? "/audit" : "/cases"} replace />;
  }

  async function onCreds(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      const r = await api.login(username.trim(), password);
      setPassword("");
      if (r.stage === "mfa_required") {
        setStep({ kind: "mfa", token: r.token });
      } else if (r.stage === "mfa_setup_required") {
        const s = await api.mfaSetup(r.token);
        setStep({ kind: "setup", token: r.token, secret: s.secret, uri: s.otpauth_uri });
      }
    });
  }

  async function onCode(e: FormEvent) {
    e.preventDefault();
    if (step.kind === "creds") return;
    const token = step.token;
    const enrolling = step.kind === "setup";
    await run(async () => {
      const r = enrolling ? await api.mfaEnable(token, code) : await api.mfaVerify(token, code);
      await startSession(r.token);
    });
    setCode("");
  }

  function back() {
    clear();
    setStep({ kind: "creds" });
    setCode("");
  }

  return (
    <div className="authwrap">
      <div className="authcard">
        <h1>SDMS</h1>
        <p className="muted" style={{ marginTop: 0 }}>Secure Digital Document Management for legal &amp; investigation records</p>
        <Msg error={error} />

        {step.kind === "creds" && (
          <form onSubmit={onCreds}>
            <div className="field">
              <label htmlFor="u">Username</label>
              <input id="u" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required />
            </div>
            <div className="field">
              <label htmlFor="p">Password</label>
              <input id="p" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </div>
            <button className="btn" disabled={busy} style={{ width: "100%" }}>{busy ? "Checking…" : "Continue"}</button>
          </form>
        )}

        {step.kind !== "creds" && (
          <form onSubmit={onCode}>
            {step.kind === "setup" && (
              <>
                <p><strong>Set up two-factor authentication.</strong> Scan this code with an authenticator app (Google Authenticator, Microsoft Authenticator, FreeOTP…), then enter the 6-digit code it shows.</p>
                <div className="qr"><QRCodeSVG value={step.uri} size={172} /></div>
                <p className="small muted">Can't scan? Enter this key manually:</p>
                <div className="secret mono" style={{ marginBottom: 12 }}>{step.secret}</div>
              </>
            )}
            {step.kind === "mfa" && <p><strong>Two-factor check.</strong> Enter the 6-digit code from your authenticator app.</p>}
            <div className="field">
              <label htmlFor="c">Authentication code</label>
              <input
                id="c" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                inputMode="numeric" autoComplete="one-time-code" maxLength={6} pattern="\d{6}" autoFocus required
              />
            </div>
            <div className="actions">
              <button className="btn" disabled={busy || code.length !== 6}>{busy ? "Verifying…" : step.kind === "setup" ? "Enable & sign in" : "Sign in"}</button>
              <button type="button" className="btn secondary" onClick={back}>Back</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
