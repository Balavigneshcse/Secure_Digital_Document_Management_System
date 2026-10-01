import { useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, isSystemAdmin, ROLE_LABEL, SHARE_ROLES, type Role } from "./api";
import { useAuth } from "./auth";
import AuditPage from "./pages/Audit";
import CaseDetail from "./pages/CaseDetail";
import CasesPage from "./pages/Cases";
import CertificatePage from "./pages/Certificate";
import ChangePassword from "./pages/ChangePassword";
import Dashboard from "./pages/Dashboard";
import DocumentDetail from "./pages/DocumentDetail";
import LedgerPage from "./pages/Ledger";
import Login from "./pages/Login";
import SearchPage from "./pages/Search";
import UsersPage from "./pages/Users";

const CASE_ROLES: Role[] = ["officer", "admin", ...SHARE_ROLES];
const CONTENT_ROLES: Role[] = ["officer", ...SHARE_ROLES];
const CERT_ROLES: Role[] = ["officer", "judge", "prosecutor"];

/** Unread alerts in the top bar; refreshed every minute and whenever the dashboard marks them read. */
function AlertBell() {
  const [n, setN] = useState(0);
  const loc = useLocation();
  useEffect(() => {
    let live = true;
    const load = () => api.alerts().then((a) => { if (live) setN(a.unread); }).catch(() => { /* not fatal */ });
    void load();
    const t = window.setInterval(load, 60_000);
    window.addEventListener("sdms-alerts-seen", load);
    return () => { live = false; window.clearInterval(t); window.removeEventListener("sdms-alerts-seen", load); };
  }, [loc.pathname]);
  return (
    <Link to="/#alerts" className={`bell ${n ? "hot" : ""}`} title={n ? `${n} new alert(s)` : "No new alerts"} aria-label={`Alerts: ${n} new`}>
      🔔{n > 0 && <span className="count">{n}</span>}
    </Link>
  );
}

function Shell() {
  const { user, loading, logout } = useAuth();
  const nav = useNavigate();
  if (loading) return <div className="page spinner">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password) return <Navigate to="/change-password" replace />;
  const sys = isSystemAdmin(user);

  const links: [string, string, boolean][] = [
    ["/", "Dashboard", true],
    ["/cases", "Cases", CASE_ROLES.includes(user.role) && !sys],
    ["/search", "Search", CASE_ROLES.includes(user.role) && !sys],
    ["/users", sys ? "Users" : "Officers", user.role === "admin"],
    ["/audit", "Audit log", user.role === "auditor"],
    ["/ledger", "Integrity ledger", user.role === "auditor"],
  ];
  return (
    <>
      <header className="topbar noprint">
        <div className="brand">SDMS<small>Secure Digital Document Management</small></div>
        <nav className="nav">
          {links.filter(([, , show]) => show).map(([to, text]) => <NavLink key={to} to={to} end={to === "/"}>{text}</NavLink>)}
        </nav>
        <div className="who">
          <AlertBell />
          <span>{user.full_name}{user.station_name ? ` · ${user.station_name}` : ""}</span>
          <span className="role">{sys ? "system admin" : ROLE_LABEL[user.role].toLowerCase()}</span>
          <button className="btn secondary small" onClick={async () => { await logout(); nav("/login"); }}>Sign out</button>
        </div>
      </header>
      <main className="page"><Outlet /></main>
    </>
  );
}

function RoleGate({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user } = useAuth();
  if (!user) return null;
  return roles.includes(user.role) ? <>{children}</> : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/change-password" element={<ChangePassword />} />
      <Route element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="/cases" element={<RoleGate roles={CASE_ROLES}><CasesPage /></RoleGate>} />
        <Route path="/cases/:id" element={<RoleGate roles={CASE_ROLES}><CaseDetail /></RoleGate>} />
        <Route path="/documents/:id" element={<RoleGate roles={CONTENT_ROLES}><DocumentDetail /></RoleGate>} />
        <Route path="/documents/:id/certificate/:v" element={<RoleGate roles={CERT_ROLES}><CertificatePage /></RoleGate>} />
        <Route path="/search" element={<RoleGate roles={CASE_ROLES}><SearchPage /></RoleGate>} />
        <Route path="/users" element={<RoleGate roles={["admin"]}><UsersPage /></RoleGate>} />
        <Route path="/audit" element={<RoleGate roles={["auditor"]}><AuditPage /></RoleGate>} />
        <Route path="/ledger" element={<RoleGate roles={["auditor"]}><LedgerPage /></RoleGate>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
