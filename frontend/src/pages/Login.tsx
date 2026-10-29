import { useState, type FormEvent } from "react";
import { post, type Bootstrap, type User } from "../api";
import { IconFlask, IconInfo } from "../components/Icons";
import { Spinner } from "../components/ui";

function Art({ boot }: { boot: Bootstrap }) {
  return (
    <div className="login-art" aria-hidden="true">
      <img className="word" src="/brand/wordmark.png" alt="" />
      <img className="mark" src="/brand/monogram.png" alt="" />
      <div className="stack">
        <span className="accent-bar" />
        <p>
          One place to print from — every printer in the office, the same simple steps. {boot.settings.station_subtitle}
        </p>
      </div>
    </div>
  );
}

export default function LoginPage({ boot, onSignedIn }: { boot: Bootstrap; onSignedIn: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ user: User }>("/api/auth/login", { username, password });
      onSignedIn(r.user);
    } catch (err: any) {
      setError(err.message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <Art boot={boot} />
      <div className="login-form">
        <div className="stack" style={{ gap: 6 }}>
          <span className="eyebrow">{boot.station ? "Print station" : "Office print hub"}</span>
          <h1>{boot.settings.station_name}</h1>
        </div>
        {boot.mode === "demo" && (
          <div className="callout callout-sim">
            <IconFlask />
            <span>
              <b>Demo mode.</b> Printers and jobs are simulated — nothing will be printed.
            </span>
          </div>
        )}
        {boot.needs_admin_setup && (
          <div className="callout callout-info">
            <IconInfo />
            <span>
              No administrator account exists yet. On the station, run <code>sudo -u printhub printhub create-admin &lt;name&gt;</code>.
            </span>
          </div>
        )}
        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="u">Username</label>
            <input id="u" className="input" autoComplete="username" autoCapitalize="none" spellCheck={false}
              value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </div>
          <div className="field">
            <label htmlFor="p">Password</label>
            <input id="p" className="input" type="password" autoComplete="current-password"
              value={password} onChange={(e) => setPassword(e.target.value)} required aria-invalid={!!error} />
          </div>
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
          <button className="btn btn-primary btn-lg btn-block" disabled={busy || !username || !password}>
            {busy ? <Spinner /> : "Sign in"}
          </button>
        </form>
        <p className="subtle">
          {boot.station
            ? `On this shared station you'll be signed out automatically after ${boot.settings.station_idle_logout_minutes} minutes of inactivity.`
            : "Forgot your password? Ask an office administrator to reset it."}
        </p>
      </div>
    </div>
  );
}

export function ChangePasswordPage({ boot, user, onDone, onCancel }: { boot: Bootstrap; user: User; onDone: (u: User) => void; onCancel: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mismatch = repeat.length > 0 && next !== repeat;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== repeat) return;
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ user: User }>("/api/auth/password", { current_password: current, new_password: next });
      onDone(r.user);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <Art boot={boot} />
      <div className="login-form">
        <div className="stack" style={{ gap: 6 }}>
          <span className="eyebrow">Welcome, {user.display_name}</span>
          <h1>Choose your password</h1>
          <p className="muted">You signed in with a temporary password. Pick your own to continue (at least 8 characters).</p>
        </div>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="cur">Temporary password</label>
            <input id="cur" className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="new">New password</label>
            <input id="new" className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="rep">Repeat new password</label>
            <input id="rep" className="input" type="password" autoComplete="new-password" value={repeat} aria-invalid={mismatch}
              onChange={(e) => setRepeat(e.target.value)} />
            {mismatch && <span className="field-error">The passwords don't match.</span>}
          </div>
          {error && <p className="field-error" role="alert">{error}</p>}
          <div className="row">
            <button className="btn btn-primary btn-lg" disabled={busy || !current || next.length < 8 || mismatch}>
              {busy ? <Spinner /> : "Save password"}
            </button>
            <button type="button" className="btn btn-ghost" onClick={onCancel}>
              Sign out
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
