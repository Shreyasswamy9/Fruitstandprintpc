import { useCallback, useEffect, useState } from "react";
import { get, type Job } from "../../api";
import { Segmented, useInterval } from "../../components/ui";
import { JobRow } from "../Jobs";

export default function AdminQueue() {
  const [filter, setFilter] = useState<"active" | "all">("active");
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(
    () =>
      get<{ jobs: Job[] }>(`/api/jobs?scope=all&limit=200${filter === "active" ? "&status=active" : ""}`)
        .then((r) => {
          setJobs(r.jobs);
          setError(null);
        })
        .catch((e) => setError(e.message)),
    [filter],
  );
  useEffect(() => {
    load();
  }, [load]);
  useInterval(load, 4000);
  return (
    <div className="stack-lg">
      <div className="row-between">
        <p className="muted" style={{ maxWidth: "70ch" }}>
          Every job on this station. File names are hidden from administrators to keep employees' documents private; open a job to cancel it or
          see its full technical timeline.
        </p>
        <div style={{ width: 260 }}>
          <Segmented label="Filter" value={filter} onChange={setFilter} options={[{ key: "active", label: "Active" }, { key: "all", label: "Recent" }]} />
        </div>
      </div>
      {error && <div className="callout callout-bad">{error}</div>}
      {jobs && jobs.length === 0 && <div className="card empty">{filter === "active" ? "Nothing is printing right now." : "No jobs yet."}</div>}
      <div className="job-list">{jobs?.map((j, i) => <JobRow key={j.id} job={j} index={i} showOwner />)}</div>
    </div>
  );
}
