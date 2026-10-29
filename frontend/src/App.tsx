import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { get, onAuthError, post, type Bootstrap, type User } from "./api";
import { Hub, useHub, type HubContext } from "./context";
import { IconExpand, IconFlask, IconList, IconPrinter, IconSettings } from "./components/Icons";
import { Spinner, useToast } from "./components/ui";
import LoginPage, { ChangePasswordPage } from "./pages/Login";
import PrintPage from "./pages/Print";
import JobsPage from "./pages/Jobs";
import JobDetailPage from "./pages/JobDetail";
import AdminPage from "./pages/Admin";

const THEME_KEY = "printhub.theme";

function readThemeOverride(): string | null {
  try {
    return localStorage.getItem(THEME_KEY);
  } catch {
    return null;
  }
}

export default function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [bootError, setBootError] = useState<string | null>(null);
  const [themeOverride, setThemeOverrideState] = useState<string | null>(readThemeOverride);
  const toast = useToast();

  const reloadBoot = useCallback(async () => {
    try {
      setBoot(await get<Bootstrap>("/api/bootstrap"));
      setBootError(null);
    } catch (e: any) {
      setBootError(e.message);
    }
  }, []);

  useEffect(() => {
    reloadBoot();
    get<{ user: User | null }>("/api/auth/me")
      .then((r) => setUser(r.user))
      .catch(() => setUser(null));
  }, [reloadBoot]);

  useEffect(
    () =>
      onAuthError((err) => {
        if (err.status === 401) setUser(null);
      }),
    [],
  );

  // Appearance: station-wide default from settings, optional per-device override.
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = themeOverride ?? boot?.settings.appearance_theme ?? "system";
    root.dataset.motion = boot?.settings.appearance_motion ?? "full";
    root.dataset.density = boot?.settings.appearance_density ?? "comfortable";
    document.title = boot ? `${boot.settings.station_name} · Print` : "Print Hub";
  }, [boot, themeOverride]);

  const setThemeOverride = useCallback((t: string | null) => {
    setThemeOverrideState(t);
    try {
      if (t) localStorage.setItem(THEME_KEY, t);
      else localStorage.removeItem(THEME_KEY);
    } catch {
      /* storage unavailable: keep in memory only */
    }
  }, []);

  const logout = useCallback(
    async (reason?: string) => {
      try {
        await post("/api/auth/logout");
      } catch {
        /* already signed out */
      }
      setUser(null);
      if (reason) toast({ title: "Signed out", body: reason });
    },
    [toast],
  );

  if (bootError && !boot) {
    return (
      <div className="empty" style={{ minHeight: "100vh" }}>
        <h2>Print hub unavailable</h2>
        <p className="muted">{bootError}</p>
        <button className="btn" onClick={reloadBoot}>
          Try again
        </button>
      </div>
    );
  }
  if (!boot || user === undefined) {
    return (
      <div className="empty" style={{ minHeight: "100vh" }}>
        <Spinner label="Loading" />
      </div>
    );
  }
  if (!user) return <LoginPage boot={boot} onSignedIn={setUser} />;
  if (user.must_change_password) return <ChangePasswordPage boot={boot} user={user} onDone={setUser} onCancel={() => logout()} />;

  const ctx: HubContext = { boot, user, setUser, reloadBoot, logout, themeOverride, setThemeOverride };
  return (
    <Hub.Provider value={ctx}>
      <Shell />
    </Hub.Provider>
  );
}

function Shell() {
  const { boot, user } = useHub();
  const location = useLocation();
  const [activeJobs, setActiveJobs] = useState(0);

  useEffect(() => {
    let alive = true;
    const load = () =>
      get<{ jobs: unknown[] }>("/api/jobs?status=active&limit=50")
        .then((r) => alive && setActiveJobs(r.jobs.length))
        .catch(() => {});
    load();
    const id = window.setInterval(load, 8000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [location.pathname]);

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {boot.mode === "demo" && (
        <div className="demo-banner" role="note">
          <IconFlask size={16} />
          <strong>Demo mode</strong>
          <span>Printers and jobs are simulated. Nothing is sent to a real printer.</span>
        </div>
      )}
      <header className="header">
        <NavLink to="/" className="brand" aria-label={`${boot.settings.station_name} home`}>
          <img className="brand-mark" src="/brand/monogram.png" alt="" />
          <img className="brand-word" src="/brand/wordmark.png" alt="Fruitstand" />
          <span className="brand-station">
            <b>Print Hub</b>
            <span>{boot.settings.station_name}</span>
          </span>
        </NavLink>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>
            <IconPrinter size={18} />
            <span className="nav-label">Print</span>
          </NavLink>
          <NavLink to="/jobs">
            <IconList size={18} />
            <span className="nav-label">My jobs</span>
            {activeJobs > 0 && <span className="count" aria-label={`${activeJobs} active`}>{activeJobs}</span>}
          </NavLink>
          {user.role === "admin" && (
            <NavLink to="/admin">
              <IconSettings size={18} />
              <span className="nav-label">Admin</span>
            </NavLink>
          )}
        </nav>
        <UserMenu />
      </header>
      {user.station && <StationIdle />}
      <main id="main" className="main" key={location.pathname.split("/").slice(0, 2).join("/")}>
        <Routes>
          <Route path="/" element={<PrintPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/admin/*" element={user.role === "admin" ? <AdminPage /> : <Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function UserMenu() {
  const { user, boot, logout, themeOverride, setThemeOverride } = useHub();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  const initials = user.display_name
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const fullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen?.().catch(() => {});
    setOpen(false);
  };
  const cycleTheme = () => {
    const order = [null, "light", "dark"];
    setThemeOverride(order[(order.indexOf(themeOverride) + 1) % order.length]);
  };
  return (
    <div className="user-menu" ref={ref}>
      <button className="avatar" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} aria-label="Account menu">
        {initials || "?"}
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-head">
            <b>{user.display_name}</b>
            <div className="subtle">
              {user.username} · {user.role === "admin" ? "Administrator" : "Employee"}
              {user.station && " · at the station"}
            </div>
          </div>
          <button role="menuitem" onClick={fullscreen}>
            <IconExpand size={16} /> {document.fullscreenElement ? "Exit full screen" : "Full screen"}
          </button>
          <button role="menuitem" onClick={cycleTheme}>
            Theme on this device: {themeOverride ?? `station default (${boot.settings.appearance_theme})`}
          </button>
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false);
              navigate("/jobs");
            }}
          >
            My jobs
          </button>
          <button role="menuitem" onClick={() => logout()}>
            Sign out
          </button>
          <div className="subtle" style={{ padding: "8px 12px" }}>
            Print Hub {boot.version}
          </div>
        </div>
      )}
    </div>
  );
}

/** On the shared station, sign people out after a period of inactivity. */
function StationIdle() {
  const { boot, logout } = useHub();
  const limit = boot.settings.station_idle_logout_minutes * 60;
  const last = useRef(Date.now());
  const [remaining, setRemaining] = useState<number | null>(null);
  useEffect(() => {
    const bump = () => {
      last.current = Date.now();
      setRemaining(null);
    };
    const events = ["mousemove", "mousedown", "keydown", "wheel", "touchstart"];
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }));
    const id = window.setInterval(() => {
      const left = Math.round(limit - (Date.now() - last.current) / 1000);
      if (left <= 0) logout("You were signed out of the station after a period of inactivity.");
      else setRemaining(left <= 30 ? left : null);
    }, 1000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, bump));
      window.clearInterval(id);
    };
  }, [limit, logout]);
  const text = useMemo(() => (remaining ? `Signing out in ${remaining}s — move the pointer or press a key to stay.` : null), [remaining]);
  if (!text) return null;
  return (
    <div className="demo-banner" style={{ background: "var(--accent)" }} role="alert">
      {text}
    </div>
  );
}
