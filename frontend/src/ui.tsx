import { useCallback, useEffect, useState, type ReactNode } from "react";
import { errText } from "./api";

export function Alert({ kind, children }: { kind: "ok" | "err" | "warn"; children: ReactNode }) {
  return <div className={`alert ${kind}`} role={kind === "err" ? "alert" : "status"}>{children}</div>;
}

export function Badge({ kind, children }: { kind?: "ok" | "warn" | "err"; children: ReactNode }) {
  return <span className={`badge ${kind ?? ""}`}>{children}</span>;
}

export function Chips({ items }: { items: string[] }) {
  return items.length ? <div className="chips">{items.map((i) => <span className="chip" key={i}>{i}</span>)}</div> : <span className="muted">—</span>;
}

/** Loads data on mount / when `deps` change; exposes reload + error state. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    setLoading(true);
    return fn().then((d) => { setData(d); setError(null); }).catch((e) => setError(errText(e))).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { void load(); }, [load]);
  return { data, error, loading, reload: load, setData };
}

/** Wraps an async action with busy + error/ok message state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const run = useCallback(async <T,>(fn: () => Promise<T>, okMsg?: string | ((result: T) => string)): Promise<T | undefined> => {
    setBusy(true); setError(null); setOk(null);
    try {
      const r = await fn();
      if (okMsg) setOk(typeof okMsg === "function" ? okMsg(r) : okMsg);
      return r;
    } catch (e) {
      setError(errText(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, ok, run, clear: () => { setError(null); setOk(null); } };
}

export function Msg({ error, ok }: { error?: string | null; ok?: string | null }) {
  return <>{error && <Alert kind="err">{error}</Alert>}{ok && <Alert kind="ok">{ok}</Alert>}</>;
}

export function Loading({ loading, error }: { loading: boolean; error: string | null }) {
  if (error) return <Alert kind="err">{error}</Alert>;
  return loading ? <div className="spinner">Loading…</div> : null;
}
