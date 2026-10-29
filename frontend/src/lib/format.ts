import type { ItemStatus, JobStatus, PrinterState } from "../api";

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function plural(n: number, one: string, many = one + "s"): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function time(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

export function dateTime(ts: number | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? `Today ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 10) return "just now";
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export type Tone = "ok" | "warn" | "bad" | "info" | "unknown" | "sim" | "live" | "neutral";

export const PRINTER_TONE: Record<PrinterState, Tone> = {
  ready: "ok",
  busy: "info",
  attention: "warn",
  stopped: "bad",
  offline: "bad",
  unknown: "unknown",
  disabled: "neutral",
};

/**
 * Status wording is deliberate: the hub can only see what the print system
 * reports. "Completed" never claims that paper came out of the printer.
 */
export function jobStatus(status: JobStatus, simulated: boolean): { label: string; detail: string; tone: Tone } {
  const sim = simulated ? " (simulated)" : "";
  switch (status) {
    case "submitting":
      return { label: "Sending to the print queue", detail: "The hub is handing your files to the print system.", tone: "live" };
    case "in_progress":
      return { label: "In the print queue" + sim, detail: "The print system has your job and is working through it.", tone: "live" };
    case "completed":
      return simulated
        ? { label: "Simulation finished", detail: "Demo mode — nothing was sent to a real printer and no paper was used.", tone: "sim" }
        : {
            label: "Print system reports done",
            detail: "The printer queue says this job finished. The hub can't see paper — collect it from the printer to confirm.",
            tone: "ok",
          };
    case "partial":
      return { label: "Partly done", detail: "Some files finished and some did not. See each file below.", tone: "warn" };
    case "failed":
      return { label: "Didn't print", detail: "The print system did not accept or could not finish this job.", tone: "bad" };
    case "cancelled":
      return { label: "Cancelled", detail: "This job was cancelled.", tone: "neutral" };
    case "unknown":
      return {
        label: "Outcome unknown",
        detail: "The hub lost track of this job. Check the printer before printing again so you don't get duplicates.",
        tone: "unknown",
      };
  }
}

export function itemStatus(status: ItemStatus, simulated: boolean): { label: string; tone: Tone } {
  const map: Record<ItemStatus, { label: string; tone: Tone }> = {
    ready: { label: "Waiting to send", tone: "neutral" },
    submitting: { label: "Sending…", tone: "live" },
    queued: { label: "Waiting in queue", tone: "info" },
    held: { label: "Held in queue", tone: "warn" },
    processing: { label: "Sending to printer", tone: "live" },
    stopped: { label: "Stopped at printer", tone: "warn" },
    completed: simulated ? { label: "Simulated · done", tone: "sim" } : { label: "Reported done", tone: "ok" },
    cancelled: { label: "Cancelled", tone: "neutral" },
    failed: { label: "Failed", tone: "bad" },
    unknown: { label: "Outcome unknown", tone: "unknown" },
  };
  return map[status];
}

export const ACTIVE_JOB: JobStatus[] = ["submitting", "in_progress"];

export function chipClass(tone: Tone): string {
  return (
    {
      ok: "chip chip-ok",
      warn: "chip chip-warn",
      bad: "chip chip-bad",
      info: "chip chip-info",
      unknown: "chip chip-unknown",
      sim: "chip chip-sim",
      live: "chip chip-accent chip-live",
      neutral: "chip",
    } as const
  )[tone];
}
