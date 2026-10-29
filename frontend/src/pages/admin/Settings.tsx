import { useEffect, useState } from "react";
import { get, patch } from "../../api";
import { IconInfo } from "../../components/Icons";
import { Segmented, Spinner, useToast } from "../../components/ui";
import { useHub } from "../../context";

interface AllSettings {
  station_name: string;
  station_subtitle: string;
  file_retention_hours: number;
  history_retention_days: number;
  event_retention_days: number;
  station_idle_logout_minutes: number;
  job_title_style: "reference" | "filename";
  appearance_theme: "system" | "light" | "dark";
  appearance_motion: "full" | "reduced";
  appearance_density: "comfortable" | "compact";
}

export default function AdminSettings() {
  const { boot, reloadBoot } = useHub();
  const toast = useToast();
  const [s, setS] = useState<AllSettings | null>(null);
  const [saved, setSaved] = useState<AllSettings | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get<{ settings: AllSettings }>("/api/admin/settings").then((r) => {
      setS(r.settings);
      setSaved(r.settings);
    });
  }, []);
  if (!s || !saved) return <div className="skeleton" style={{ height: 300 }} />;

  const dirty = JSON.stringify(s) !== JSON.stringify(saved);
  const set = <K extends keyof AllSettings>(k: K, v: AllSettings[K]) => setS({ ...s, [k]: v });
  const save = async () => {
    setBusy(true);
    try {
      const changes = Object.fromEntries(Object.entries(s).filter(([k, v]) => saved[k as keyof AllSettings] !== v));
      const r = await patch<{ settings: AllSettings }>("/api/admin/settings", changes);
      setS(r.settings);
      setSaved(r.settings);
      await reloadBoot();
      toast({ title: "Settings saved" });
    } catch (e: any) {
      toast({ title: "Not saved", body: e.details ? Object.entries(e.details).map(([k, v]) => `${k}: ${v}`).join("; ") : e.message, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };
  const num = (k: keyof AllSettings, min: number, max: number) => (
    <input className="input" type="number" min={min} max={max} value={s[k] as number}
      onChange={(e) => set(k, Math.round(Number(e.target.value)) as any)} />
  );

  return (
    <div className="stack-lg">
      <div className="two-col">
        <section className="card card-pad stack">
          <h3>Station</h3>
          <div className="field">
            <label htmlFor="sn">Station name</label>
            <input id="sn" className="input" maxLength={60} value={s.station_name} onChange={(e) => set("station_name", e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="ss">Subtitle</label>
            <input id="ss" className="input" maxLength={80} value={s.station_subtitle} onChange={(e) => set("station_subtitle", e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="si">Sign out at the station after (minutes idle)</label>
            {num("station_idle_logout_minutes", 1, 120)}
          </div>
          <div className="field">
            <span className="field-label">Job name shown on printer panels</span>
            <Segmented label="Job name" value={s.job_title_style} onChange={(v) => set("job_title_style", v)}
              options={[{ key: "reference", label: "Name + reference", sub: "e.g. Alice · Hub 3FA2C1" }, { key: "filename", label: "File name", sub: "Visible to anyone at the printer" }]} />
          </div>
        </section>

        <section className="card card-pad stack">
          <h3>Retention</h3>
          <div className="field">
            <label htmlFor="rf">Keep uploaded files for (hours)</label>
            {num("file_retention_hours", 1, 720)}
            <span className="field-hint">Files in a job that is still printing are kept until it finishes. Reprinting needs the file, so it's possible only within this window.</span>
          </div>
          <div className="field">
            <label htmlFor="rh">Keep job history for (days)</label>
            {num("history_retention_days", 1, 3650)}
          </div>
          <div className="field">
            <label htmlFor="re">Keep diagnostic events for (days)</label>
            {num("event_retention_days", 1, 365)}
            <span className="field-hint">The JSON log file rotates separately: 5 files × 5 MB by default.</span>
          </div>
        </section>
      </div>

      <section className="card card-pad stack">
        <h3>Appearance</h3>
        <div className="form-grid">
          <div className="field">
            <span className="field-label">Theme</span>
            <Segmented label="Theme" value={s.appearance_theme} onChange={(v) => set("appearance_theme", v)}
              options={[{ key: "system", label: "System" }, { key: "light", label: "Light" }, { key: "dark", label: "Dark" }]} />
          </div>
          <div className="field">
            <span className="field-label">Motion</span>
            <Segmented label="Motion" value={s.appearance_motion} onChange={(v) => set("appearance_motion", v)}
              options={[{ key: "full", label: "Full" }, { key: "reduced", label: "Reduced" }]} />
          </div>
          <div className="field">
            <span className="field-label">Density</span>
            <Segmented label="Density" value={s.appearance_density} onChange={(v) => set("appearance_density", v)}
              options={[{ key: "comfortable", label: "Comfortable" }, { key: "compact", label: "Compact" }]} />
          </div>
        </div>
        <p className="subtle">People's own reduced-motion system setting is always respected. Each device can override the theme from the account menu.</p>
      </section>

      <section className="card card-pad stack">
        <h3>Software & maintenance</h3>
        <dl className="summary-list">
          <dt>Version</dt>
          <dd>Print Hub {boot.version} · {boot.mode} mode</dd>
          <dt>Updates</dt>
          <dd className="muted">Run <span className="mono">sudo /opt/printhub/current/deploy/update.sh &lt;release&gt;</span> on the station. It backs up the database, installs side by side, and rolls back automatically if the health check fails. See docs/OPERATIONS.md.</dd>
          <dt>Exit the dashboard</dt>
          <dd className="muted">
            At the station: <kbd>Esc</kbd> leaves full screen; <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Q</kbd> (or <kbd>Alt</kbd>+<kbd>F4</kbd>) closes the dashboard window. Reopen it from the “Print Hub” desktop icon or by signing out and in.
          </dd>
          <dt>Printer firmware</dt>
          <dd className="muted">Firmware updates are manufacturer-specific and are done with each printer's own tools. The hub doesn't update firmware.</dd>
        </dl>
      </section>

      <div className="action-bar" style={{ margin: 0, borderRadius: "var(--radius-card)", border: "1px solid var(--line)" }}>
        <span className="grow subtle">
          <IconInfo size={14} style={{ display: "inline", verticalAlign: "-2px" }} /> {dirty ? "You have unsaved changes." : "All changes saved."}
        </span>
        <button className="btn" disabled={!dirty || busy} onClick={() => setS(saved)}>
          Discard
        </button>
        <button className="btn btn-primary" disabled={!dirty || busy} onClick={save}>
          {busy ? <Spinner /> : "Save settings"}
        </button>
      </div>
    </div>
  );
}
