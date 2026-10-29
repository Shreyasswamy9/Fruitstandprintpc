import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { get, newKey, post, type ApiError, type Job, type TimelineEvent } from "../api";
import { IconAlert, IconBan, IconCheck, IconClock, IconFlask, IconQuestion, IconRefresh } from "../components/Icons";
import { Chip, Dialog, Spinner, useInterval, useToast } from "../components/ui";
import { useHub } from "../context";
import { ACTIVE_JOB, dateTime, itemStatus, jobStatus, time } from "../lib/format";

function StatusIcon({ tone }: { tone: string }) {
  if (tone === "ok") return <IconCheck />;
  if (tone === "bad") return <IconAlert />;
  if (tone === "unknown") return <IconQuestion />;
  if (tone === "sim") return <IconFlask />;
  if (tone === "neutral") return <IconBan />;
  return <IconClock />;
}

export default function JobDetailPage() {
  const { id } = useParams();
  const { user } = useHub();
  const toast = useToast();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDupes, setConfirmDupes] = useState<number[] | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);

  const load = useCallback(async () => {
    try {
      const [j, t] = await Promise.all([get<{ job: Job }>(`/api/jobs/${id}`), get<{ events: TimelineEvent[] }>(`/api/jobs/${id}/timeline`)]);
      setJob(j.job);
      setEvents(t.events);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);
  const live = job ? ACTIVE_JOB.includes(job.status) : false;
  useInterval(load, live ? 1500 : null);

  if (error && !job) {
    return (
      <div className="page card empty">
        <h3>Job not found</h3>
        <p>{error}</p>
        <Link className="btn" to="/jobs">
          Back to my jobs
        </Link>
      </div>
    );
  }
  if (!job) return <div className="skeleton" style={{ height: 300 }} />;

  const st = jobStatus(job.status, job.simulated);

  const cancel = async () => {
    setConfirmCancel(false);
    setBusy("cancel");
    try {
      const r = await post<{ job: Job }>(`/api/jobs/${job.id}/cancel`);
      setJob(r.job);
      const results = r.job.cancel_results ?? [];
      const notDone = results.filter((x) => x.result === "not_cancelled");
      toast({
        title: notDone.length ? "Some files couldn't be cancelled" : "Cancellation sent",
        body: results.map((x) => `File ${x.position + 1}: ${x.message}`).join(" "),
        tone: notDone.length ? "warn" : "default",
      });
      load();
    } catch (e: any) {
      toast({ title: "Cancel failed", body: e.message, tone: "bad" });
    } finally {
      setBusy(null);
    }
  };

  const retry = async (confirm = false) => {
    setBusy("retry");
    try {
      const r = await post<{ job: Job }>(`/api/jobs/${job.id}/retry`, { confirm_possible_duplicates: confirm });
      setJob(r.job);
      setConfirmDupes(null);
      toast({ title: "Retrying", body: "Only files that didn't reach the printer queue are being resent." });
      load();
    } catch (e: any) {
      const err = e as ApiError;
      if (err.code === "confirm_duplicates") setConfirmDupes(err.details?.positions ?? []);
      else toast({ title: "Retry not possible", body: err.message, tone: "bad" });
    } finally {
      setBusy(null);
    }
  };

  const reprint = async () => {
    setBusy("reprint");
    try {
      const r = await post<{ job: Job }>(`/api/jobs/${job.id}/reprint`, { idempotency_key: newKey() });
      toast({ title: "Reprint sent", body: `New job ${r.job.reference}` });
      navigate(`/jobs/${r.job.id}`);
    } catch (e: any) {
      toast({ title: "Reprint failed", body: e.message, tone: "bad" });
    } finally {
      setBusy(null);
    }
  };


  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="eyebrow">
            Job {job.reference}
            {!job.own && job.owner ? ` · ${job.owner.display_name}` : ""}
          </span>
          <h1>{st.label}</h1>
        </div>
        <div className="row">
          <Link className="btn btn-ghost" to={job.own ? "/jobs" : "/admin/queue"}>
            Back
          </Link>
          {job.can_cancel && (
            <button className="btn btn-danger" onClick={() => setConfirmCancel(true)} disabled={!!busy}>
              {busy === "cancel" ? <Spinner /> : "Cancel"}
            </button>
          )}
          {job.can_retry && (job.own || user.role === "admin") && (
            <button className="btn" onClick={() => retry(false)} disabled={!!busy}>
              {busy === "retry" ? <Spinner /> : (<><IconRefresh size={16} /> Retry failed</>)}
            </button>
          )}
          {job.own && !live && (
            <button className="btn" onClick={reprint} disabled={!!busy || !job.can_reprint}
              title={job.can_reprint ? "" : job.files_retained ? "The printer is unavailable" : "The files have been deleted under the retention policy"}>
              {busy === "reprint" ? <Spinner /> : "Print again"}
            </button>
          )}
        </div>
      </div>

      {job.simulated && (
        <div className="callout callout-sim" style={{ marginBottom: 20 }}>
          <IconFlask />
          <span>Simulated job (demo mode). No printer received it and nothing was printed.</span>
        </div>
      )}

      <div className="detail-grid">
        <div className="stack-lg">
          <div className="card">
            <div className="status-hero">
              <span className="status-ring" data-tone={st.tone}>
                <StatusIcon tone={st.tone} />
              </span>
              <div className="stack" style={{ gap: 4 }}>
                <b>{job.printer?.display_name ?? "Printer removed"}</b>
                <span className="muted">{st.detail}</span>
                {job.status === "completed" && !job.simulated && (
                  <span className="subtle">Pages don't appear? Check the printer for paper or a jam, then use “Print again”.</span>
                )}
              </div>
            </div>
            <ol className="item-list">
              {job.items.map((item) => {
                const is = itemStatus(item.status, job.simulated);
                return (
                  <li key={item.id}>
                    <span className="item-n">{item.position + 1}</span>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 650, wordBreak: "break-word" }}>{item.name}</div>
                      <div className="subtle">
                        {item.page_ranges ? `Pages ${item.page_ranges}` : item.pages ? `All ${item.pages} page${item.pages === 1 ? "" : "s"}` : ""}
                        {item.backend_job_id ? ` · queue job ${item.backend_job_id}` : ""}
                        {item.attempts > 1 ? ` · ${item.attempts} attempts` : ""}
                      </div>
                      {item.message && <div className="muted" style={{ fontSize: "0.85rem", marginTop: 4 }}>{item.message}</div>}
                      {item.reasons.filter((r) => !r.keyword.startsWith("job-")).map((r) => (
                        <div key={r.keyword} className="printer-warn" style={{ marginTop: 4 }}>
                          <IconAlert size={14} /> {r.explanation}
                        </div>
                      ))}
                      {!item.file_available && <div className="subtle">File deleted (retention) — reprint not possible.</div>}
                    </div>
                    <Chip tone={is.tone}>{is.label}</Chip>
                  </li>
                );
              })}
            </ol>
          </div>

          <div className="card card-pad">
            <h3 style={{ marginBottom: 12 }}>Settings used</h3>
            <dl className="summary-list">
              {job.preset_name && (
                <>
                  <dt>Preset</dt>
                  <dd>{job.preset_name}</dd>
                </>
              )}
              {job.settings_display.length === 0 && (
                <>
                  <dt>All</dt>
                  <dd>Printer defaults</dd>
                </>
              )}
              {job.settings_display.map(([label, value]) => (
                <span key={label} style={{ display: "contents" }}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </span>
              ))}
              <dt>Submitted</dt>
              <dd>{dateTime(job.created_at)}</dd>
              {job.reprint_of && (
                <>
                  <dt>Reprint of</dt>
                  <dd>
                    <Link to={`/jobs/${job.reprint_of}`}>{job.reprint_of.slice(0, 6).toUpperCase()}</Link>
                  </dd>
                </>
              )}
            </dl>
          </div>
        </div>

        <div className="card card-pad">
          <div className="row-between" style={{ marginBottom: 16 }}>
            <h3>Timeline</h3>
            {live && (
              <Chip tone="live">Live</Chip>
            )}
          </div>
          <ol className="timeline">
            {events.map((e, i) => (
              <li key={i} data-level={e.level} data-event={e.event}>
                <time>{time(e.ts)}</time>
                <div className="t-msg">{e.message}</div>
                {e.details && Object.keys(e.details).length > 0 && (
                  <details className="tech">
                    <summary>Technical details</summary>
                    <pre>{JSON.stringify(e.details, null, 2)}</pre>
                  </details>
                )}
              </li>
            ))}
          </ol>
          <p className="subtle">Reference for support: <span className="mono">{job.correlation_id}</span></p>
        </div>
      </div>

      {confirmCancel && (
        <Dialog title="Cancel this job?" size="sm" onClose={() => setConfirmCancel(false)}
          footer={<>
            <button className="btn" onClick={() => setConfirmCancel(false)}>Keep printing</button>
            <button className="btn btn-primary" onClick={cancel} data-autofocus>Cancel job</button>
          </>}>
          <p className="muted">Files still waiting will be removed from the queue. A file that is already printing may finish some pages before it stops; anything already finished can't be cancelled.</p>
        </Dialog>
      )}
      {confirmDupes && (
        <Dialog title="These files may already have printed" size="sm" onClose={() => setConfirmDupes(null)}
          footer={<>
            <button className="btn" onClick={() => setConfirmDupes(null)}>Don't resend</button>
            <button className="btn btn-primary" onClick={() => retry(true)} disabled={busy === "retry"}>Resend anyway</button>
          </>}>
          <p className="muted">
            File{confirmDupes.length === 1 ? "" : "s"} {confirmDupes.map((p) => p + 1).join(", ")} reached the print system before something went wrong, so pages may
            already be in the printer tray. Check the printer first. Resending could produce duplicates.
          </p>
        </Dialog>
      )}
    </div>
  );
}
