import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { errText } from "./lib";
import Library from "./pages/Library";
import NewTemplate from "./pages/NewTemplate";
import TemplateDetail from "./pages/TemplateDetail";
import CopyEditor from "./pages/CopyEditor";
import Generate from "./pages/Generate";
import Runs from "./pages/Runs";
import RunDetail from "./pages/RunDetail";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/templates", label: "Templates", icon: "M3 3h4v4H3zM9 3h4v4H9zM3 9h4v4H3zM9 9h4v4H9z" },
  { to: "/templates/new", label: "New template", icon: "M8 3v10M3 8h10" },
  { to: "/generate", label: "Generate", icon: "M3 13l4-4 3 3 3-6" },
  { to: "/runs", label: "Results", icon: "M3 3h10v10H3zM3 7h10" },
  { to: "/settings", label: "Settings", icon: "M8 5a3 3 0 100 6 3 3 0 000-6zM8 1v2M8 13v2M1 8h2M13 8h2" },
];

function Mark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#16130F" />
      <path d="M9 7c8 4 6 14 14 18M23 7c-8 4-6 14-14 18" stroke="#C8102E" strokeWidth="2.4" fill="none" />
    </svg>
  );
}

function Login({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [err, setErr] = useState("");
  return (
    <main className="main" style={{ maxWidth: 460, margin: "10vh auto" }}>
      <div className="card">
        <h1>Sign in</h1>
        <p className="muted">This workspace is protected. Enter the access token set by its administrator (DNA_AUTH_TOKEN).</p>
        <form onSubmit={async (e) => { e.preventDefault(); try { await api.post("/api/auth/login", { token }); onDone(); } catch (x) { setErr(errText(x)); } }}>
          <label className="field"><span className="label">Access token</span>
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus autoComplete="current-password" /></label>
          {err && <p className="notice bad" role="alert">{err}</p>}
          <button className="btn" type="submit">Sign in</button>
        </form>
      </div>
    </main>
  );
}

export default function App() {
  const [auth, setAuth] = useState<{ required: boolean; authenticated: boolean } | null>(null);
  const [menu, setMenu] = useState(false);
  const [mock, setMock] = useState(false);
  const loc = useLocation();
  const check = () => api.get<{ required: boolean; authenticated: boolean }>("/api/auth/status").then(setAuth).catch(() => setAuth({ required: false, authenticated: true }));
  useEffect(() => { check(); const h = () => setAuth({ required: true, authenticated: false }); window.addEventListener("dna:unauthorized", h); return () => window.removeEventListener("dna:unauthorized", h); }, []);
  useEffect(() => { setMenu(false); }, [loc.pathname]);
  useEffect(() => { if (auth?.authenticated) api.get<any>("/api/providers").then((ps) => setMock(ps.some((p: any) => p.mock))).catch(() => {}); }, [auth]);
  if (!auth) return null;
  if (auth.required && !auth.authenticated) return <Login onDone={check} />;
  return (
    <div className="shell">
      <header className="topbar">
        <button className="btn ghost small" aria-expanded={menu} aria-controls="sidebar" onClick={() => setMenu(!menu)}>☰ Menu</button>
        <span className="brand-name">Design DNA</span>
        <span />
      </header>
      <nav id="sidebar" className={`sidebar ${menu ? "open" : ""}`} aria-label="Main">
        <NavLink to="/templates" className="brand" end>
          <Mark />
          <span><span className="brand-name">Design DNA</span><span className="brand-sub">template library</span></span>
        </NavLink>
        <div className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/templates"}>
              <svg className="nav-ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><path d={n.icon} /></svg>
              {n.label}
            </NavLink>
          ))}
        </div>
        <div className="sidebar-foot">
          <p>Measured templates, verified edits.</p>
          {auth.required && <button className="btn ghost small" onClick={async () => { await api.post("/api/auth/logout"); check(); }}>Sign out</button>}
        </div>
      </nav>
      <main className="main" id="main">
        {mock && <div className="banner crimson" role="note">Mock providers are enabled (test mode). Their proposals and images are labelled “mock” and are not real analysis or generation.</div>}
        <Routes>
          <Route path="/" element={<Navigate to="/templates" replace />} />
          <Route path="/templates" element={<Library />} />
          <Route path="/templates/new" element={<NewTemplate />} />
          <Route path="/templates/:id" element={<TemplateDetail />} />
          <Route path="/templates/:id/edit" element={<CopyEditor />} />
          <Route path="/generate" element={<Generate />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<div className="empty"><h2>Page not found</h2><p><a href="/templates">Back to the library</a></p></div>} />
        </Routes>
      </main>
    </div>
  );
}
