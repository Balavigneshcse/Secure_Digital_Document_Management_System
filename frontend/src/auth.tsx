import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, hasToken, setToken, setUnauthorizedHandler, tokenExpiresAt, type User } from "./api";

const RENEW_WITHIN_MS = 8 * 60 * 1000; // renew when the token has less than this left...
const ACTIVE_WITHIN_MS = 10 * 60 * 1000; // ...but only if the user did something recently (an idle session should expire)

interface AuthCtx {
  user: User | null;
  loading: boolean;
  /** Called after a full (post-MFA) login with the access token. */
  startSession: (token: string) => Promise<User>;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(hasToken());

  const clear = useCallback(() => { setToken(null); setUser(null); }, []);
  const lastActivity = useRef(Date.now());

  // Sliding session: while the user is working, swap the token for a fresh one before it expires. The server caps the
  // whole session at a fixed length, so this can never keep a login alive indefinitely.
  useEffect(() => {
    if (!user) return;
    const touch = () => { lastActivity.current = Date.now(); };
    window.addEventListener("pointerdown", touch);
    window.addEventListener("keydown", touch);
    const timer = window.setInterval(() => {
      const exp = tokenExpiresAt();
      if (exp && exp - Date.now() < RENEW_WITHIN_MS && Date.now() - lastActivity.current < ACTIVE_WITHIN_MS) {
        api.refresh().then((r) => setToken(r.token)).catch(() => { /* a 401 here logs out through the normal handler */ });
      }
    }, 60_000);
    return () => { window.clearInterval(timer); window.removeEventListener("pointerdown", touch); window.removeEventListener("keydown", touch); };
  }, [user]);

  useEffect(() => {
    setUnauthorizedHandler(clear);
    if (!hasToken()) return;
    api.me().then(setUser).catch(clear).finally(() => setLoading(false));
  }, [clear]);

  const value = useMemo<AuthCtx>(() => ({
    user,
    loading,
    async startSession(token) {
      setToken(token);
      const u = await api.me();
      setUser(u);
      return u;
    },
    async refresh() { setUser(await api.me()); },
    async logout() {
      try { await api.logout(); } catch { /* token may already be invalid */ }
      clear();
    },
  }), [user, loading, clear]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
