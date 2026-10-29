import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get, type Job } from "../api";
import { IconFile, IconFlask, IconPrinter } from "../components/Icons";
import { Chip, useInterval } from "../components/ui";
import { ACTIVE_JOB, dateTime, jobStatus, plural } from "../lib/format";

export function JobRow({ job, index = 0, showOwner = false }: { job: Job; index?: number; showOwner?: boolean }) {
  const st = jobStatus(job.status, job.simulated);
  const names = job.items.map((i) => i.name);
  return (
    <Link to={`/jobs/${job.id}`} className="job-row" style={{ animationDelay: `${Math.min(index, 8) * 30}ms` }}>
      <span className="job-icon">{job.simulated ? <IconFlask /> : <IconFile />}</span>
      <span style={{ minWidth: 0 }}>
        <div className="job-title">
          {names[0]}
          {names.length > 1 ? ` + ${plural(names.length - 1, "more file")}` : ""}
        </div>
        <div className="job-sub">
          <IconPrinter size={13} style={{ display: "inline", verticalAlign: "-2px" }} /> {job.printer?.display_name ?? "Removed printer"} ·{" "}
          {dateTime(job.created_at)} · {job.reference}
          {showOwner && job.owner ? ` · ${job.owner.display_name}` : ""}
        </div>
      </span>
      {job.attention && job.status === "in_progress" ? <Chip tone="warn">Needs attention</Chip> : <span />}
      <Chip tone={st.tone}>{st.label}</Chip>
    </Link>
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(
    () =>
      get<{ jobs: Job[] }>("/api/jobs?limit=100")
        .then((r) => {
          setJobs(r.jobs);
          setError(null);
        })
        .catch((e) => setError(e.message)),
    [],
  );
  useEffect(() => {
    load();
  }, [load]);
  const active = jobs?.filter((j) => ACTIVE_JOB.includes(j.status)) ?? [];
  const done = jobs?.filter((j) => !ACTIVE_JOB.includes(j.status)) ?? [];
  useInterval(load, active.length ? 3000 : 15000);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="eyebrow">Queue & history</span>
          <h1>My jobs</h1>
          <p>Only you can see these. “Reported done” means the printer queue finished the job — collect your pages to confirm they printed.</p>
        </div>
        <Link to="/" className="btn btn-primary">
          New print
        </Link>
      </div>
      {error && <div className="callout callout-bad">{error}</div>}
      {!jobs && !error && <div className="skeleton" style={{ height: 200 }} />}
      {jobs && jobs.length === 0 && (
        <div className="card empty">
          <h3>No jobs yet</h3>
          <p>Jobs you print will show up here so you can track, cancel or reprint them.</p>
        </div>
      )}
      {active.length > 0 && (
        <section className="stack" style={{ marginBottom: 32 }}>
          <h3>In progress</h3>
          <div className="job-list">
            {active.map((j, i) => (
              <JobRow key={j.id} job={j} index={i} />
            ))}
          </div>
        </section>
      )}
      {done.length > 0 && (
        <section className="stack">
          <h3>History</h3>
          <div className="job-list">
            {done.map((j, i) => (
              <JobRow key={j.id} job={j} index={i} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
