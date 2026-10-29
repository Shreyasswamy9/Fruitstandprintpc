"""Administrator diagnostics: health, event search and support reports."""
from __future__ import annotations

import os
import platform
import shutil
import sys
import time
from typing import Any

from . import __version__
from .db import loads

EVENT_HELP = {
    "upload.received": "A browser started sending a file to the hub.",
    "upload.accepted": "The file passed content checks (real type, size, page/pixel limits) and is stored privately.",
    "upload.rejected": "The file was refused before it could be printed. The reason code says why.",
    "job.created": "The person confirmed printing. Settings were validated against the printer's live capabilities.",
    "job.duplicate_blocked": "The same confirmation arrived twice (double-click or network retry). No second job was created.",
    "job.settings_rejected": "Requested settings were not supported by the printer, so nothing was sent.",
    "item.prepared": "The file was readied for the print system (a converted copy is used when noted).",
    "submission.attempt": "The hub handed the file to CUPS with the listed options.",
    "submission.accepted": "CUPS accepted the file and returned a job number. This does not prove paper came out.",
    "submission.failed": "CUPS did not accept the file. Nothing from this attempt is waiting in the queue unless marked uncertain.",
    "job.queued": "Waiting in the CUPS queue.",
    "job.held": "Held in the CUPS queue (for example, by an administrator).",
    "job.processing": "CUPS is converting and sending the job to the printer.",
    "job.stopped": "CUPS paused the job, usually because the printer reported a problem.",
    "job.completed": "CUPS reports the job finished. Most printers do not confirm physical output beyond this point.",
    "job.failed": "CUPS aborted the job. Some pages may have printed before it stopped.",
    "job.cancelled": "The job was cancelled in CUPS.",
    "job.lost": "CUPS no longer reports this job (purged history or scheduler restart). Its final outcome is unknown.",
    "job.stuck": "The job has waited longer than expected. Check the printer for paper, jams or errors.",
    "cancel.requested": "Someone asked to cancel this job.",
    "cancel.done": "CUPS confirmed the cancellation.",
    "cancel.local": "The file was cancelled before the hub sent it.",
    "cancel.failed": "CUPS could not cancel the job; it may have already finished.",
    "retry.requested": "Only files that did not reach the print system are resent, unless duplicates were explicitly confirmed.",
    "printer.status": "The printer's reported state changed.",
    "capabilities.read": "The hub read the printer's supported options from CUPS.",
    "capabilities.failed": "The printer's options could not be read; printing to it is blocked until they can be.",
    "printsystem.unreachable": "CUPS is not answering. Job tracking pauses; new jobs will fail until it recovers.",
    "printsystem.reachable": "CUPS is answering again.",
    "service.started": "The hub service started.",
    "service.stopped": "The hub service stopped cleanly.",
    "service.unclean_restart": "The previous run ended without a clean shutdown (crash, power loss or kill).",
    "item.recovered": "After a restart, an in-flight file was settled to a safe state instead of being resent automatically.",
    "file.deleted": "A stored upload was removed.",
    "cleanup.completed": "Scheduled retention cleanup ran.",
    "auth.login": "Successful sign-in.",
    "auth.login_failed": "A sign-in attempt failed.",
    "auth.locked": "Sign-in temporarily blocked after repeated failures.",
}


def dir_size(path) -> tuple[int, int]:
    total = count = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
                count += 1
    except FileNotFoundError:
        pass
    return total, count


class Diagnostics:
    def __init__(self, app_state):
        self.s = app_state

    def health(self) -> dict[str, Any]:
        s = self.s
        checks: list[dict[str, Any]] = []
        try:
            queues = s.registry.adapter.list_queues()
            checks.append({"name": "Print system", "ok": True,
                           "detail": f"{'Simulated print system' if s.config.demo else 'CUPS'} responding · {len(queues)} queue(s)"})
        except Exception as exc:  # AdapterError or unexpected
            checks.append({"name": "Print system", "ok": False, "detail": getattr(exc, "message", str(exc))})
        try:
            s.db.one("SELECT 1 AS ok")
            checks.append({"name": "Database", "ok": True, "detail": f"Schema v{s.db.schema_version} · {s.config.db_path}"})
        except Exception as exc:
            checks.append({"name": "Database", "ok": False, "detail": str(exc)})
        usage = shutil.disk_usage(s.config.data_dir)
        free_pct = usage.free / usage.total * 100
        checks.append({"name": "Disk space", "ok": free_pct > 10 and usage.free > 1 << 30,
                       "detail": f"{usage.free / (1 << 30):.1f} GB free ({free_pct:.0f}%)"})
        for name, last, interval in (
            ("Job tracking loop", s.loop_runs.get("poll"), s.config.poll_interval_s),
            ("Printer status loop", s.loop_runs.get("status"), s.config.status_interval_s),
            ("Cleanup loop", s.loop_runs.get("cleanup"), s.config.cleanup_interval_s),
        ):
            if not s.config.background_tasks:
                checks.append({"name": name, "ok": None, "detail": "Background tasks disabled in this process"})
                continue
            age = time.time() - last if last else None
            ok = age is not None and age < interval * 3 + 30
            checks.append({"name": name, "ok": ok, "detail": f"Last ran {age:.0f}s ago" if age is not None else "Has not run yet"})
        upload_bytes, upload_count = dir_size(s.config.upload_dir)
        log_bytes, log_count = dir_size(s.config.log_dir)
        active = s.db.one("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('submitting', 'in_progress')")["n"]
        printers = [s.registry.public(r, admin=True) for r in s.registry.rows(include_disabled=True)]
        return {
            "version": __version__,
            "mode": s.config.mode,
            "uptime_s": round(time.time() - s.started_at),
            "started_at": s.started_at,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "checks": checks,
            "storage": {"uploads_bytes": upload_bytes, "uploads_files": upload_count,
                        "logs_bytes": log_bytes, "log_files": log_count,
                        "db_bytes": s.config.db_path.stat().st_size if s.config.db_path.exists() else 0},
            "active_jobs": active,
            "printers": [{"id": p["id"], "name": p["display_name"], "status": p["status"],
                          "capabilities_error": p["capabilities_error"], "connection": p.get("connection")} for p in printers],
            "paths": {"data": str(s.config.data_dir), "logs": str(s.config.log_dir),
                      "app_log": str(s.config.log_dir / "printhub.jsonl")},
            "visibility_note": ("Printer status comes from CUPS and the printer's own reports. Many printers do not report "
                                "jams, paper or physical output; unreported conditions are shown as unknown, never as healthy."),
        }

    def search(self, *, q: str = "", level: str = "", category: str = "", printer_id: str = "", job_id: str = "",
               correlation_id: str = "", since: float | None = None, until: float | None = None,
               before_id: int | None = None, limit: int = 100) -> dict[str, Any]:
        clauses, params = [], []
        if q:
            like = f"%{q}%"
            clauses.append("(message LIKE ? OR event LIKE ? OR correlation_id LIKE ? OR job_id LIKE ? OR details LIKE ?)")
            params += [like] * 5
        if level:
            order = ["debug", "info", "warning", "error"]
            allowed = order[order.index(level):] if level in order else order
            clauses.append(f"level IN ({','.join('?' * len(allowed))})")
            params += allowed
        for col, val in (("category", category), ("printer_id", printer_id), ("job_id", job_id), ("correlation_id", correlation_id)):
            if val:
                clauses.append(f"{col} = ?")
                params.append(val)
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if until:
            clauses.append("ts <= ?")
            params.append(until)
        if before_id:
            clauses.append("id < ?")
            params.append(before_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        limit = max(1, min(limit, 500))
        rows = self.s.db.all(f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?", (*params, limit + 1))
        more = len(rows) > limit
        rows = rows[:limit]
        return {
            "events": [self._event(r) for r in rows],
            "next_before_id": rows[-1]["id"] if more and rows else None,
        }

    def _event(self, r: dict) -> dict[str, Any]:
        return {
            "id": r["id"], "ts": r["ts"], "level": r["level"], "category": r["category"], "event": r["event"],
            "message": r["message"], "correlation_id": r["correlation_id"], "job_id": r["job_id"],
            "item_id": r["item_id"], "printer_id": r["printer_id"],
            "user": f"user-{r['user_id']}" if r["user_id"] else None,
            "details": loads(r["details"], {}),
            "help": EVENT_HELP.get(r["event"]),
        }

    def report(self, days: int = 3, correlation_id: str = "") -> dict[str, Any]:
        since = time.time() - days * 86400
        events = self.search(since=since, correlation_id=correlation_id, limit=500)["events"]
        jobs = self.s.db.all(
            "SELECT id, correlation_id, printer_id, status, simulated, created_at, finished_at,"
            " (SELECT COUNT(*) FROM job_items i WHERE i.job_id = jobs.id) AS files FROM jobs WHERE created_at >= ? ORDER BY created_at DESC LIMIT 500",
            (since,),
        )
        settings = self.s.settings.all()
        return {
            "report": "Fruitstand Print Hub support report",
            "generated_at": time.time(),
            "redaction": ("Usernames are replaced by user-<id>; file names, document contents, passwords and session tokens "
                          "are never included."),
            "window_days": days,
            "health": self.health(),
            "settings": settings,
            "jobs": jobs,
            "events": events,
        }
