import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get, post, type DiagEvent, type PrinterState } from "../../api";
import { IconDownload, IconInfo, IconRefresh, IconSearch } from "../../components/Icons";
import { Chip, Spinner, useInterval, useToast } from "../../components/ui";
import { ago, bytes, PRINTER_TONE, time } from "../../lib/format";

interface Health {
  version: string;
  mode: string;
  uptime_s: number;
  python: string;
  platform: string;
  checks: { name: string; ok: boolean | null; detail: string }[];
  storage: { uploads_bytes: number; uploads_files: number; logs_bytes: number; log_files: number; db_bytes: number };
  active_jobs: number;
  printers: { id: string; name: string; status: { state: PrinterState; label: string; error: string | null; checked_at: number | null }; capabilities_error: string | null; connection?: string }[];
  paths: { data: string; logs: string; app_log: string };
  visibility_note: string;
}

const CATEGORIES = ["", "upload", "validation", "preparation", "capability", "submission", "job_state", "printer", "cancel", "retry", "timeout", "auth", "admin", "service", "cleanup"];

function uptime(s: number) {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

export default function AdminDiagnostics() {
  const toast = useToast();
  const [health, setHealth] = useState<Health | null>(null);
  const [events, setEvents] = useState<DiagEvent[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({ q: "", level: "", category: "", correlation_id: "" });
  const [cleaning, setCleaning] = useState(false);

  const loadHealth = useCallback(() => get<Health>("/api/admin/diagnostics/health").then(setHealth).catch(() => {}), []);
  const search = useCallback(
    async (before?: number) => {
      setLoading(true);
      const params = new URLSearchParams({ limit: "100" });
      Object.entries(filters).forEach(([k, v]) => v && params.set(k, v));
      if (before) params.set("before_id", String(before));
      try {
        const r = await get<{ events: DiagEvent[]; next_before_id: number | null }>(`/api/admin/diagnostics/events?${params}`);
        setEvents((prev) => (before ? [...prev, ...r.events] : r.events));
        setNext(r.next_before_id);
      } finally {
        setLoading(false);
      }
    },
    [filters],
  );
  useEffect(() => {
    loadHealth();
  }, [loadHealth]);
  useEffect(() => {
    const t = window.setTimeout(() => search(), 250);
    return () => window.clearTimeout(t);
  }, [search]);
  useInterval(loadHealth, 10000);

  const cleanup = async () => {
    setCleaning(true);
    try {
      const r = await post<Record<string, number>>("/api/admin/maintenance/cleanup");
      toast({ title: "Cleanup finished", body: `${r.removed} files removed, ${r.kept_for_active_jobs} kept for active jobs, ${r.events_purged} old events purged.` });
      loadHealth();
    } finally {
      setCleaning(false);
    }
  };

  return (
    <div className="stack-lg">
      <section className="stack">
        <div className="row-between">
          <h3>Service health</h3>
          <div className="row">
            <button className="btn btn-sm" onClick={loadHealth}>
              <IconRefresh size={14} /> Refresh
            </button>
            <button className="btn btn-sm" onClick={cleanup} disabled={cleaning}>
              {cleaning ? <Spinner /> : "Run cleanup now"}
            </button>
            <a className="btn btn-sm btn-primary" href="/api/admin/diagnostics/report?days=3" download>
              <IconDownload size={14} /> Support report
            </a>
          </div>
        </div>
        {health ? (
          <>
            <div className="health-grid">
              {health.checks.map((c) => (
                <div className="health-card" key={c.name}>
                  <span className={`ind ${c.ok === true ? "ind-ok" : c.ok === false ? "ind-bad" : "ind-unknown"}`} aria-hidden="true" />
                  <div>
                    <b>{c.name}</b>
                    <div className="subtle">{c.ok === false ? "Problem · " : c.ok === null ? "Not monitored · " : ""}{c.detail}</div>
                  </div>
                </div>
              ))}
              <div className="health-card">
                <span className="ind ind-ok" aria-hidden="true" />
                <div>
                  <b>Print Hub {health.version}</b>
                  <div className="subtle">
                    {health.mode} mode · up {uptime(health.uptime_s)} · {health.active_jobs} active job(s)
                  </div>
                </div>
              </div>
            </div>
            <div className="two-col">
              <div className="card card-pad stack">
                <h3>Printers</h3>
                {health.printers.map((p) => (
                  <div key={p.id} className="row-between" style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                    <div>
                      <b>{p.name}</b>
                      <div className="subtle">
                        {p.connection} · checked {ago(p.status.checked_at)}
                      </div>
                      {(p.status.error || p.capabilities_error) && <div className="subtle">{p.status.error ?? p.capabilities_error}</div>}
                    </div>
                    <Chip tone={PRINTER_TONE[p.status.state]}>{p.status.label}</Chip>
                  </div>
                ))}
                <div className="callout callout-info">
                  <IconInfo />
                  <span>{health.visibility_note}</span>
                </div>
              </div>
              <div className="card card-pad stack">
                <h3>Storage & logs</h3>
                <dl className="summary-list">
                  <dt>Uploads</dt>
                  <dd>
                    {health.storage.uploads_files} files · {bytes(health.storage.uploads_bytes)}
                  </dd>
                  <dt>Database</dt>
                  <dd>{bytes(health.storage.db_bytes)}</dd>
                  <dt>App log</dt>
                  <dd>
                    <span className="mono">{health.paths.app_log}</span>
                    <div className="subtle">
                      {health.storage.log_files} file(s) · {bytes(health.storage.logs_bytes)} · rotated automatically
                    </div>
                  </dd>
                  <dt>Service log</dt>
                  <dd className="mono">journalctl -u printhub</dd>
                  <dt>CUPS logs</dt>
                  <dd className="mono">/var/log/cups/error_log · page_log</dd>
                  <dt>Platform</dt>
                  <dd className="subtle">
                    {health.platform} · Python {health.python}
                  </dd>
                </dl>
              </div>
            </div>
          </>
        ) : (
          <div className="skeleton" style={{ height: 140 }} />
        )}
      </section>

      <section className="stack">
        <h3>Event log</h3>
        <div className="filters card card-pad">
          <div className="field">
            <label htmlFor="dq">Search</label>
            <div style={{ position: "relative" }}>
              <IconSearch size={16} style={{ position: "absolute", left: 12, top: 14, opacity: 0.5 }} />
              <input id="dq" className="input" style={{ paddingLeft: 36 }} placeholder="Message, job, CUPS job number…" value={filters.q}
                onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
            </div>
          </div>
          <div className="field">
            <label htmlFor="dl">Minimum level</label>
            <select id="dl" className="select" value={filters.level} onChange={(e) => setFilters({ ...filters, level: e.target.value })}>
              <option value="">All</option>
              <option value="info">Info and above</option>
              <option value="warning">Warnings and errors</option>
              <option value="error">Errors only</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="dc">Category</label>
            <select id="dc" className="select" value={filters.category} onChange={(e) => setFilters({ ...filters, category: e.target.value })}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c ? c.replace("_", " ") : "All"}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="dcorr">Correlation ID</label>
            <input id="dcorr" className="input mono" placeholder="c-…" value={filters.correlation_id}
              onChange={(e) => setFilters({ ...filters, correlation_id: e.target.value.trim() })} />
          </div>
          <button className="btn" onClick={() => setFilters({ q: "", level: "", category: "", correlation_id: "" })}>
            Clear
          </button>
        </div>

        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Level</th>
                <th>Event</th>
                <th>Links</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td className="subtle" style={{ whiteSpace: "nowrap" }}>
                    {new Date(e.ts * 1000).toLocaleDateString([], { month: "short", day: "numeric" })} {time(e.ts)}
                  </td>
                  <td>
                    <Chip tone={e.level === "error" ? "bad" : e.level === "warning" ? "warn" : "neutral"}>{e.level}</Chip>
                  </td>
                  <td style={{ minWidth: 320 }}>
                    <b>{e.message}</b>
                    <div className="subtle mono">
                      {e.category} · {e.event}
                      {e.user ? ` · ${e.user}` : ""}
                    </div>
                    {e.help && <div className="subtle">{e.help}</div>}
                    {Object.keys(e.details).length > 0 && (
                      <details className="tech">
                        <summary>Technical details</summary>
                        <pre>{JSON.stringify(e.details, null, 2)}</pre>
                      </details>
                    )}
                  </td>
                  <td className="subtle" style={{ whiteSpace: "nowrap" }}>
                    {e.job_id && (
                      <div>
                        <Link to={`/jobs/${e.job_id}`}>Job {e.job_id.slice(0, 6).toUpperCase()}</Link>
                      </div>
                    )}
                    {e.correlation_id && (
                      <button className="link-btn mono" onClick={() => setFilters({ ...filters, correlation_id: e.correlation_id! })}>
                        {e.correlation_id}
                      </button>
                    )}
                    {e.printer_id && <div>{e.printer_id}</div>}
                  </td>
                </tr>
              ))}
              {!events.length && !loading && (
                <tr>
                  <td colSpan={4} className="subtle">
                    No events match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {next && (
          <button className="btn" onClick={() => search(next)} disabled={loading} style={{ alignSelf: "center" }}>
            {loading ? <Spinner /> : "Load older events"}
          </button>
        )}
      </section>
    </div>
  );
}
