import type { ReactNode } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import type { Role } from "./api";
import { useAuth } from "./auth";
import AuditPage from "./pages/Audit";
import CaseDetail from "./pages/CaseDetail";
import CasesPage from "./pages/Cases";
import ChangePassword from "./pages/ChangePassword";
import DocumentDetail from "./pages/DocumentDetail";
import LedgerPage from "./pages/Ledger";
import Login from "./pages/Login";
import SearchPage from "./pages/Search";
import UsersPage from "./pages/Users";

const home = (role: Role) => (role === "auditor" ? "/audit" : "/cases");

function Shell() {
  const { user, loading, logout } = useAuth();
  const nav = useNavigate();
  if (loading) return <div className="page spinner">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password) return <Navigate to="/change-password" replace />;

  const links: [string, string, Role[]][] = [
    ["/cases", "Cases", ["officer", "admin", "forensic", "judge"]],
    ["/search", "Search", ["officer", "admin", "forensic", "judge"]],
    ["/users", "Officers", ["admin"]],
    ["/audit", "Audit log", ["auditor"]],
    ["/ledger", "Integrity ledger", ["auditor"]],
  ];
  return (
    <>
      <header className="topbar">
        <div className="brand">SDMS<small>Secure Digital Document Management</small></div>
        <nav className="nav">
          {links.filter(([, , roles]) => roles.includes(user.role)).map(([to, text]) => (
            <NavLink key={to} to={to}>{text}</NavLink>
          ))}
        </nav>
        <div className="who">
          <span>{user.full_name}{user.station_name ? ` · ${user.station_name}` : ""}</span>
          <span className="role">{user.role}</span>
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
  return roles.includes(user.role) ? <>{children}</> : <Navigate to={home(user.role)} replace />;
}

function Home() {
  const { user } = useAuth();
  return <Navigate to={user ? home(user.role) : "/login"} replace />;
}

export default function App() {
  const caseRoles: Role[] = ["officer", "admin", "forensic", "judge"];
  const contentRoles: Role[] = ["officer", "forensic", "judge"];
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/change-password" element={<ChangePassword />} />
      <Route element={<Shell />}>
        <Route index element={<Home />} />
        <Route path="/cases" element={<RoleGate roles={caseRoles}><CasesPage /></RoleGate>} />
        <Route path="/cases/:id" element={<RoleGate roles={caseRoles}><CaseDetail /></RoleGate>} />
        <Route path="/documents/:id" element={<RoleGate roles={contentRoles}><DocumentDetail /></RoleGate>} />
        <Route path="/search" element={<RoleGate roles={caseRoles}><SearchPage /></RoleGate>} />
        <Route path="/users" element={<RoleGate roles={["admin"]}><UsersPage /></RoleGate>} />
        <Route path="/audit" element={<RoleGate roles={["auditor"]}><AuditPage /></RoleGate>} />
        <Route path="/ledger" element={<RoleGate roles={["auditor"]}><LedgerPage /></RoleGate>} />
      </Route>
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
