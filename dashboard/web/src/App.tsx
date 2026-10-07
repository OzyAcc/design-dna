import { useEffect, useState } from "react";
import {
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { api } from "./api";
import { errText, useLocal } from "./lib";
import { Dialog, Icon, type IconName } from "./components/ui";
import CommandMenu from "./components/CommandMenu";
import Library from "./pages/Library";
import NewTemplate from "./pages/NewTemplate";
import TemplateDetail from "./pages/TemplateDetail";
import CopyEditor from "./pages/CopyEditor";
import Generate from "./pages/Generate";
import Runs from "./pages/Runs";
import RunDetail from "./pages/RunDetail";
import Settings from "./pages/Settings";

const NAV: { to: string; label: string; icon: IconName; group: string }[] = [
  { to: "/templates", label: "Templates", icon: "layers", group: "Library" },
  {
    to: "/templates/new",
    label: "New template",
    icon: "plus",
    group: "Library",
  },
  { to: "/generate", label: "Generate", icon: "sparkles", group: "Create" },
  { to: "/runs", label: "Results", icon: "results", group: "Create" },
];

function Mark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <Icon name="layers" size={22} />
    </span>
  );
}

function Navigation({
  collapsed = false,
  onCollapse,
  authRequired,
  onLogout,
}: {
  collapsed?: boolean;
  onCollapse?: () => void;
  authRequired: boolean;
  onLogout: () => void;
}) {
  return (
    <>
      <div className="sidebar-brand">
        <NavLink to="/templates" className="brand" end>
          <Mark />
          <span className="brand-wordmark">
            <span className="brand-name">
              Design DNA<span className="brand-period">.</span>
            </span>
            <span className="brand-sub">Your design workspace</span>
          </span>
        </NavLink>
      </div>
      <div className="workspace-chip">
        <span className="workspace-avatar">D</span>
        <span className="nav-label">
          <strong>My workspace</strong>
          <small>Template studio</small>
        </span>
        <Icon name="chevron" size={13} />
      </div>
      <nav className="nav" aria-label="Main">
        {["Library", "Create"].map((group) => (
          <div className="nav-group" key={group}>
            <span className="label nav-group-label">{group}</span>
            {NAV.filter((n) => n.group === group).map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/templates"}
                title={collapsed ? n.label : undefined}
              >
                <Icon name={n.icon} className="nav-ico" />
                <span className="nav-label">{n.label}</span>
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-guide">
        <Icon name="book" />
        <strong>Start with a design.</strong>
        <p>Scan it once. Make it yours. Reuse it with any product.</p>
        <Link to="/templates/new">
          Create a template <Icon name="arrow" size={14} />
        </Link>
      </div>
      <div className="sidebar-foot">
        <NavLink
          className="sidebar-settings"
          to="/settings"
          title={collapsed ? "Settings" : undefined}
        >
          <Icon name="settings" />
          <span className="nav-label">Settings</span>
        </NavLink>
        <div className="sidebar-bottom">
          <span className="nav-label workspace-note">
            <span className="dot ok" />
            Workspace
          </span>
          {onCollapse && (
            <button
              className="btn ghost icon-btn"
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={onCollapse}
            >
              <Icon name="panel" size={16} />
            </button>
          )}
        </div>
        {authRequired && (
          <button className="btn ghost small" onClick={onLogout}>
            Sign out
          </button>
        )}
      </div>
    </>
  );
}

function Login({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <main className="login-page">
      <div className="login-art" aria-hidden="true">
        <Icon name="layers" size={68} />
        <h2>
          A design worth
          <br />
          making your own.
        </h2>
        <p>One reference. A library of possibilities.</p>
      </div>
      <div className="login-card">
        <div className="brand">
          <Mark />
          <span className="brand-name">Design DNA.</span>
        </div>
        <span className="label">Your workspace awaits</span>
        <h1>Welcome back.</h1>
        <p className="muted">Enter your workspace access token to continue.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setErr("");
            try {
              await api.post("/api/auth/login", { token });
              onDone();
            } catch (x) {
              setErr(errText(x));
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="field">
            <span className="label">Access token</span>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoFocus
              autoComplete="current-password"
              required
            />
          </label>
          {err && (
            <p className="notice bad" role="alert">
              {err}
            </p>
          )}
          <button className="btn accent" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Open workspace"}
            <Icon name="arrow" />
          </button>
        </form>
        <p className="small muted login-hint">
          Your administrator provides this token.
        </p>
      </div>
    </main>
  );
}

export default function App() {
  const [auth, setAuth] = useState<{
    required: boolean;
    authenticated: boolean;
  } | null>(null);
  const [menu, setMenu] = useState(false);
  const [command, setCommand] = useState(false);
  const [collapsed, setCollapsed] = useLocal("dna.sidebar.collapsed", false);
  const [theme, setTheme] = useLocal("dna.theme", "light");
  const [mock, setMock] = useState(false);
  const loc = useLocation();
  const check = () =>
    api
      .get<{ required: boolean; authenticated: boolean }>("/api/auth/status")
      .then(setAuth)
      .catch(() => setAuth({ required: false, authenticated: true }));
  useEffect(() => {
    check();
    const h = () => setAuth({ required: true, authenticated: false });
    window.addEventListener("dna:unauthorized", h);
    return () => window.removeEventListener("dna:unauthorized", h);
  }, []);
  useEffect(() => {
    setMenu(false);
    setCommand(false);
  }, [loc.pathname]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (auth?.authenticated) {
          setMenu(false);
          setCommand((v) => !v);
        }
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [auth]);
  useEffect(() => {
    if (auth?.authenticated)
      api
        .get<any>("/api/providers")
        .then((ps) => setMock(ps.some((p: any) => p.mock)))
        .catch(() => {});
  }, [auth]);
  if (!auth)
    return (
      <div className="app-loading" role="status">
        <Icon name="layers" />
        <span>Opening your workspace…</span>
      </div>
    );
  if (auth.required && !auth.authenticated) return <Login onDone={check} />;
  const section = loc.pathname.startsWith("/settings")
    ? "Settings"
    : loc.pathname.startsWith("/runs")
      ? "Results"
      : loc.pathname.startsWith("/generate")
        ? "Generate"
        : "Template library";
  const detail =
    loc.pathname === "/templates/new"
      ? "New template"
      : loc.pathname.endsWith("/edit")
        ? "Edit copy"
        : /^\/templates\/[^/]+$/.test(loc.pathname)
          ? "Template"
          : /^\/runs\/[^/]+$/.test(loc.pathname)
            ? "Run details"
            : "";
  const logout = async () => {
    await api.post("/api/auth/logout");
    check();
  };
  return (
    <div className={`shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="sidebar" id="desktop-sidebar">
        <Navigation
          collapsed={collapsed}
          onCollapse={() => setCollapsed(!collapsed)}
          authRequired={auth.required}
          onLogout={logout}
        />
      </aside>
      <div className="workspace-main">
        <header className="workspace-header">
          <div className="header-location">
            <button
              className="btn ghost icon-btn mobile-menu"
              aria-label="Menu"
              aria-expanded={menu}
              aria-controls="sidebar"
              onClick={() => setMenu(true)}
            >
              <Icon name="menu" />
              <span className="sr-only">Menu</span>
            </button>
            <nav className="breadcrumbs" aria-label="Breadcrumb">
              <span className="muted breadcrumb-root">Workspace</span>
              <Icon name="chevron" size={12} />
              <span>{section}</span>
              {detail && (
                <>
                  <Icon name="chevron" size={12} />
                  <span className="muted">{detail}</span>
                </>
              )}
            </nav>
          </div>
          <div className="header-actions">
            <button
              className="command-trigger"
              onClick={() => setCommand(true)}
              aria-label="Search pages and templates"
            >
              <Icon name="search" size={16} />
              <span>Quick search</span>
              <kbd>⌘ / Ctrl K</kbd>
            </button>
            <button
              className="btn ghost icon-btn"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              aria-label={
                theme === "light"
                  ? "Switch to dark theme"
                  : "Switch to light theme"
              }
              title={theme === "light" ? "Dark theme" : "Light theme"}
            >
              <Icon name={theme === "light" ? "moon" : "sun"} />
            </button>
            <Link
              className="btn accent small header-create"
              to="/templates/new"
            >
              <Icon name="plus" size={15} />
              <span>New template</span>
            </Link>
          </div>
        </header>
        <main className="main" id="main" tabIndex={-1} key={loc.pathname}>
          {mock && (
            <div className="banner crimson" role="note">
              Mock providers are enabled (test mode). Their proposals and images
              are labelled “mock” and are not real analysis or generation.
            </div>
          )}
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
            <Route
              path="*"
              element={
                <div className="empty">
                  <h2>Page not found</h2>
                  <p>
                    <Link to="/templates">Back to the library</Link>
                  </p>
                </div>
              }
            />
          </Routes>
        </main>
        <footer className="workspace-footer">
          <span>Design DNA</span>
          <span>Reference → Template → Your product</span>
        </footer>
      </div>
      <Dialog
        open={menu}
        onClose={() => setMenu(false)}
        title="Workspace navigation"
        id="sidebar"
        className="nav-dialog"
      >
        <Navigation authRequired={auth.required} onLogout={logout} />
      </Dialog>
      <CommandMenu open={command} onClose={() => setCommand(false)} />
    </div>
  );
}
