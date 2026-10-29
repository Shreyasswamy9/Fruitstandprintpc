"""Print jobs: creation, submission, tracking, cancellation, retry, reprint.

A hub job holds one or more files ("items"). Each item becomes one job in
the print system. Item statuses:

  ready        validated, waiting to be sent
  submitting   being handed to the print system right now
  queued/held  accepted by the print system, waiting
  processing   the print system is sending it to the printer
  stopped      the print system has paused it (printer problem)
  completed    the print system REPORTS it finished — not proof of paper
  cancelled    cancelled (by the user, an admin, or at the printer)
  failed       not accepted, or aborted by the print system
  unknown      outcome uncertain (e.g. restart mid-submission, record lost)

Retrying only ever resends items that are known not to have reached the
print system, unless the user explicitly confirms possible duplicates.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config import Config
from .db import Database, dumps, loads, now
from .documents import FileStore
from .events import EventLog, new_correlation_id
from .printers.base import (
    JOB_ABORTED, JOB_CANCELLED, JOB_COMPLETED, JOB_HELD, JOB_PENDING, JOB_PROCESSING, JOB_STOPPED, AdapterError,
)
from .printers.capabilities import (
    SETTING_LABELS, count_selected_pages, describe_settings, normalize_page_ranges, to_ipp_options, validate_settings,
)
from .printers.explain import explain_reasons
from .registry import PrinterNotFound, PrinterRegistry
from .security import User
from .settings import Settings

PENDING_LOCAL = ("ready", "submitting")
IN_PRINT_SYSTEM = ("queued", "held", "processing", "stopped")
TERMINAL = ("completed", "cancelled", "failed", "unknown")
BACKEND_TO_ITEM = {
    JOB_PENDING: "queued", JOB_HELD: "held", JOB_PROCESSING: "processing", JOB_STOPPED: "stopped",
    JOB_CANCELLED: "cancelled", JOB_ABORTED: "failed", JOB_COMPLETED: "completed",
}
FORMAT_OF = {"application/pdf": "pdf", "image/jpeg": "jpeg", "image/png": "png"}


class JobError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


class JobService:
    def __init__(self, config: Config, db: Database, events: EventLog, files: FileStore,
                 registry: PrinterRegistry, settings: Settings):
        self.config = config
        self.db = db
        self.events = events
        self.files = files
        self.registry = registry
        self.settings = settings
        self.adapter = registry.adapter
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="submit")
        self._item_lock = threading.Lock()
        self._cups_ok: bool | None = None

    # ------------------------------------------------------------------ create
    def create(self, user: User, payload: dict[str, Any], *, reprint_of: str | None = None, run_async: bool = True) -> tuple[dict, bool]:
        key = str(payload.get("idempotency_key") or "").strip()
        if not 8 <= len(key) <= 80:
            raise JobError(400, "idempotency_key", "Missing submission key; reload the page and try again.")
        existing = self.db.one("SELECT id FROM jobs WHERE owner_id = ? AND idempotency_key = ?", (user.id, key))
        if existing:
            self.events.record("submission", "job.duplicate_blocked", "Repeated submission ignored (same submission key)",
                               job_id=existing["id"], user_id=user.id)
            return self.view(existing["id"], user), True

        items = payload.get("items") or []
        if not isinstance(items, list) or not items:
            raise JobError(400, "no_files", "Add at least one file.")
        if len(items) > self.config.max_files_per_job:
            raise JobError(400, "too_many_files", f"A job can include at most {self.config.max_files_per_job} files.")

        try:
            printer = self.registry.row(str(payload.get("printer_id") or ""))
        except PrinterNotFound:
            raise JobError(404, "printer_missing", "That printer is not available.")
        if not printer["enabled"]:
            raise JobError(409, "printer_disabled", "That printer has been disabled by an administrator.")

        correlation_id = payload.get("_correlation_id") or new_correlation_id()
        try:
            caps = self.registry.capabilities(printer["id"], refresh=True, correlation_id=correlation_id)
        except AdapterError as exc:
            raise JobError(503, "capabilities_unavailable",
                           f"Could not confirm what {printer['display_name']} supports right now: {exc.message}")

        settings, errors = validate_settings(payload.get("settings") or {}, caps)
        if errors:
            self.events.record("validation", "job.settings_rejected", "Requested settings are not supported", level="warning",
                               correlation_id=correlation_id, printer_id=printer["id"], user_id=user.id,
                               details={"errors": errors})
            raise JobError(422, "unsupported_settings", "Some settings are not supported by this printer.", {"settings": errors})

        item_rows, item_errors = [], {}
        for position, item in enumerate(items):
            file_row = self.files.get(str(item.get("file_id") or ""))
            if not file_row or file_row["owner_id"] != user.id:
                raise JobError(404, "file_missing", "One of the files is not available. It may have been removed.")
            if file_row["status"] != "ready":
                item_errors[str(position)] = f"“{file_row['original_name']}” has been deleted and can no longer be printed."
                continue
            print_mime = file_row["print_mime"] or file_row["mime"]
            fmt = FORMAT_OF.get(print_mime)
            if not caps.get("formats", {}).get(fmt, False):
                item_errors[str(position)] = f"{printer['display_name']} does not accept {fmt.upper() if fmt else print_mime} files."
                continue
            ranges, err = (None, None)
            if item.get("page_ranges"):
                if not caps.get("page_ranges"):
                    err = "This printer does not support page ranges."
                elif file_row["kind"] != "pdf":
                    err = "Page ranges apply to PDFs only."
                else:
                    ranges, err = normalize_page_ranges(item["page_ranges"], file_row["pages"])
            if err:
                item_errors[str(position)] = f"“{file_row['original_name']}”: {err}"
                continue
            item_rows.append((file_row, ranges))
        if item_errors:
            raise JobError(422, "invalid_items", "Some files can't be printed with these settings.", {"items": item_errors})

        job_id = secrets.token_hex(8)
        t = now()
        try:
            with self.db.tx() as conn:
                conn.execute(
                    "INSERT INTO jobs (id, correlation_id, owner_id, printer_id, idempotency_key, status, simulated, settings, settings_display,"
                    " preset_name, reprint_of, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (job_id, correlation_id, user.id, printer["id"], key, "submitting", int(self.adapter.simulated),
                     dumps(settings), dumps(describe_settings(settings, caps)), (payload.get("preset_name") or None), reprint_of, t, t),
                )
                for position, (file_row, ranges) in enumerate(item_rows):
                    conn.execute(
                        "INSERT INTO job_items (job_id, file_id, position, page_ranges, status) VALUES (?,?,?,?,?)",
                        (job_id, file_row["id"], position, ranges, "ready"),
                    )
                    # keep the file at least as long as the job could need it
                    conn.execute("UPDATE files SET expires_at = MAX(expires_at, ?) WHERE id = ?",
                                 (t + self.settings.get("file_retention_hours") * 3600, file_row["id"]))
        except sqlite3.IntegrityError:
            existing = self.db.one("SELECT id FROM jobs WHERE owner_id = ? AND idempotency_key = ?", (user.id, key))
            if existing:
                return self.view(existing["id"], user), True
            raise

        self.events.record(
            "submission", "job.created", "Print job created", correlation_id=correlation_id, job_id=job_id,
            printer_id=printer["id"], user_id=user.id,
            details={"files": [{"position": i, "file_id": f["id"], "kind": f["kind"], "pages": f["pages"], "page_ranges": r}
                               for i, (f, r) in enumerate(item_rows)],
                     "settings": settings, "preset": payload.get("preset_name"), "simulated": self.adapter.simulated,
                     "reprint_of": reprint_of},
        )
        if run_async:
            self._executor.submit(self._submit_pending, job_id)
        else:
            self._submit_pending(job_id)
        return self.view(job_id, user), False

    # ------------------------------------------------------------------ submit
    def _title(self, job: dict, owner: dict, file_row: dict, position: int, count: int) -> str:
        ref = job["id"][:6].upper()
        part = f" ({position + 1}/{count})" if count > 1 else ""
        if self.settings.get("job_title_style") == "filename":
            return f"{file_row['original_name']}{part}"
        first = (owner["display_name"] or owner["username"]).split()[0]
        return f"{first} · Hub {ref}{part}"

    def _submit_pending(self, job_id: str) -> None:
        try:
            job = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
            printer = self.db.one("SELECT * FROM printers WHERE id = ?", (job["printer_id"],))
            owner = self.db.one("SELECT * FROM users WHERE id = ?", (job["owner_id"],))
            settings = loads(job["settings"], {})
            items = self.db.all("SELECT * FROM job_items WHERE job_id = ? ORDER BY position", (job_id,))
            count = len(items)
            for item in items:
                with self._item_lock:
                    claimed = self.db.execute(
                        "UPDATE job_items SET status = 'submitting', attempts = attempts + 1 WHERE id = ? AND status = 'ready'",
                        (item["id"],),
                    ).rowcount
                if not claimed:
                    continue  # cancelled meanwhile, or already handled
                self._submit_item(job, printer, owner, settings, item, count)
        except Exception as exc:  # pragma: no cover - defensive
            self.events.record("service", "submit.crashed", "Unexpected error while submitting", level="error",
                               job_id=job_id, details={"error": repr(exc)[:500]})
        finally:
            self.recompute(job_id)

    def _submit_item(self, job: dict, printer: dict, owner: dict, settings: dict, item: dict, count: int) -> None:
        corr = job["correlation_id"]
        file_row = self.files.get(item["file_id"])
        ctx = dict(correlation_id=corr, job_id=job["id"], item_id=item["id"], printer_id=printer["id"], user_id=job["owner_id"])
        if not file_row or file_row["status"] != "ready":
            self._set_item(item["id"], "failed", message="The file was deleted before it could be sent.")
            self.events.record("submission", "submission.failed", "File no longer available", level="error", **ctx)
            return
        path, mime = self.files.print_path(file_row)
        options, copies = to_ipp_options(settings, item["page_ranges"])
        pages = count_selected_pages(item["page_ranges"], file_row["pages"])
        self.events.record(
            "preparation", "item.prepared", f"File {item['position'] + 1} of {count} prepared for printing", **ctx,
            details={"file_id": file_row["id"], "send_format": mime, "converted_copy": bool(file_row["print_name"]),
                     "pages_selected": pages},
        )
        self.events.record("submission", "submission.attempt", f"Sending file {item['position'] + 1} of {count} to the print system",
                           **ctx, details={"queue": printer["queue_name"], "options": options, "copies": copies,
                                           "attempt": item["attempts"] + 1, "adapter": self.adapter.name})
        try:
            sub = self.adapter.submit(printer["queue_name"], path, mime, self._title(job, owner, file_row, item["position"], count),
                                      options, copies, pages=pages)
        except AdapterError as exc:
            uncertain = bool(exc.details.get("uncertain"))
            self._set_item(item["id"], "unknown" if uncertain else "failed", message=exc.message)
            self.events.record("submission", "submission.failed", exc.message, level="error", **ctx,
                               details={"code": exc.code, **exc.details})
            return
        t = now()
        self.db.execute(
            "UPDATE job_items SET status = 'queued', backend_job_id = ?, reached_printer = 1, submitted_at = ?, message = '' WHERE id = ?",
            (sub.backend_job_id, t, item["id"]),
        )
        label = "Simulated print system accepted the job" if self.adapter.simulated else "Print system accepted the job"
        self.events.record("submission", "submission.accepted", f"{label} (job {sub.backend_job_id})", **ctx,
                           details={"backend_job_id": sub.backend_job_id, "response": sub.raw})

    def _set_item(self, item_id: int, status: str, message: str = "", reasons: list[str] | None = None) -> None:
        finished = now() if status in TERMINAL else None
        self.db.execute(
            "UPDATE job_items SET status = ?, message = ?, state_reasons = COALESCE(?, state_reasons),"
            " finished_at = COALESCE(?, finished_at), last_checked_at = ? WHERE id = ?",
            (status, message, dumps(reasons) if reasons is not None else None, finished, now(), item_id),
        )

    def recompute(self, job_id: str) -> str:
        statuses = [r["status"] for r in self.db.all("SELECT status FROM job_items WHERE job_id = ?", (job_id,))]
        if any(s in PENDING_LOCAL for s in statuses):
            status = "submitting"
        elif any(s in IN_PRINT_SYSTEM for s in statuses):
            status = "in_progress"
        elif statuses and all(s == "completed" for s in statuses):
            status = "completed"
        elif statuses and all(s == "cancelled" for s in statuses):
            status = "cancelled"
        elif statuses and all(s == "failed" for s in statuses):
            status = "failed"
        elif statuses and all(s == "unknown" for s in statuses):
            status = "unknown"
        else:
            status = "partial"
        finished = now() if status not in ("submitting", "in_progress") else None
        self.db.execute("UPDATE jobs SET status = ?, updated_at = ?, finished_at = ? WHERE id = ?",
                        (status, now(), finished, job_id))
        return status

    # ------------------------------------------------------------------ polling
    def poll_once(self) -> int:
        rows = self.db.all(
            "SELECT i.*, j.correlation_id, j.owner_id, j.printer_id FROM job_items i JOIN jobs j ON j.id = i.job_id"
            f" WHERE i.status IN ({','.join('?' * len(IN_PRINT_SYSTEM))}) AND i.backend_job_id IS NOT NULL",
            IN_PRINT_SYSTEM,
        )
        touched = set()
        for item in rows:
            ctx = dict(correlation_id=item["correlation_id"], job_id=item["job_id"], item_id=item["id"],
                       printer_id=item["printer_id"], user_id=item["owner_id"])
            try:
                state = self.adapter.job_state(item["backend_job_id"])
                self._cups_health(True)
            except AdapterError as exc:
                self._cups_health(False, exc.message)
                break
            if state is None:
                self._set_item(item["id"], "unknown",
                               message="The print system no longer has a record of this job, so its outcome is unknown. Check the printer before printing again.")
                self.events.record("job_state", "job.lost", "Print system no longer knows this job", level="warning", **ctx,
                                   details={"backend_job_id": item["backend_job_id"]})
                touched.add(item["job_id"])
                continue
            new_status = BACKEND_TO_ITEM[state.state]
            old_reasons = loads(item["state_reasons"], [])
            if new_status != item["status"] or sorted(state.reasons) != sorted(old_reasons):
                message = state.message
                if new_status == "failed":
                    message = state.message or "The print system stopped this job because of an error."
                self._set_item(item["id"], new_status, message=message, reasons=state.reasons)
                level = {"failed": "error", "stopped": "warning"}.get(new_status, "info")
                text = {
                    "completed": "Print system reports the job completed",
                    "processing": "Print system is sending the job to the printer",
                    "failed": "Print system aborted the job",
                    "cancelled": "Job cancelled in the print system",
                    "stopped": "Print system has stopped this job",
                    "held": "Job is held in the print system",
                    "queued": "Job is waiting in the print queue",
                }[new_status]
                self.events.record("job_state", f"job.{new_status}", f"File {item['position'] + 1}: {text[0].lower()}{text[1:]}", level=level, **ctx,
                                   details={"backend_job_id": item["backend_job_id"], "state": state.state,
                                            "reasons": state.reasons, "message": state.message,
                                            "pages_completed": state.pages_completed})
                touched.add(item["job_id"])
            else:
                self.db.execute("UPDATE job_items SET last_checked_at = ? WHERE id = ?", (now(), item["id"]))
            if (new_status in ("queued", "held", "stopped") and not item["stuck_warned"] and item["submitted_at"]
                    and now() - item["submitted_at"] > self.config.stuck_job_minutes * 60):
                self.db.execute("UPDATE job_items SET stuck_warned = 1 WHERE id = ?", (item["id"],))
                self.events.record("timeout", "job.stuck", f"Job has not started after {self.config.stuck_job_minutes} minutes",
                                   level="warning", **ctx, details={"status": new_status, "reasons": state.reasons})
        for job_id in touched:
            self.recompute(job_id)
        return len(rows)

    def _cups_health(self, ok: bool, error: str = "") -> None:
        if ok == self._cups_ok:
            return
        self._cups_ok = ok
        if ok:
            self.events.record("service", "printsystem.reachable", "Print system is responding")
        else:
            self.events.record("service", "printsystem.unreachable", "Print system is not responding; job tracking paused",
                               level="error", details={"error": error})

    # ------------------------------------------------------------------ actions
    def _authorize(self, job_id: str, user: User) -> dict:
        job = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not job or (job["owner_id"] != user.id and not user.is_admin):
            raise JobError(404, "job_missing", "Job not found.")
        return job

    def cancel(self, job_id: str, user: User) -> dict:
        job = self._authorize(job_id, user)
        ctx = dict(correlation_id=job["correlation_id"], job_id=job_id, printer_id=job["printer_id"], user_id=user.id)
        self.events.record("cancel", "cancel.requested", "Cancellation requested" + (" by an administrator" if job["owner_id"] != user.id else ""), **ctx)
        results = []
        for item in self.db.all("SELECT * FROM job_items WHERE job_id = ? ORDER BY position", (job_id,)):
            outcome = self._cancel_item(item, ctx)
            results.append({"position": item["position"], **outcome})
        self.recompute(job_id)
        view = self.view(job_id, user)
        view["cancel_results"] = results
        return view

    def _cancel_item(self, item: dict, ctx: dict) -> dict:
        ictx = {**ctx, "item_id": item["id"]}
        status = item["status"]
        if status == "ready":
            with self._item_lock:
                changed = self.db.execute("UPDATE job_items SET status = 'cancelled', finished_at = ?, message = ? WHERE id = ? AND status = 'ready'",
                                          (now(), "Cancelled before it was sent to the printer.", item["id"])).rowcount
            if changed:
                self.events.record("cancel", "cancel.local", "Cancelled before sending", **ictx)
                return {"result": "cancelled", "message": "Cancelled before it was sent."}
            status = self.db.one("SELECT status FROM job_items WHERE id = ?", (item["id"],))["status"]
        if status == "submitting":
            return {"result": "not_cancelled", "message": "This file is being sent right now. Try again in a moment."}
        if status in ("queued", "held", "processing", "stopped"):
            try:
                self.adapter.cancel(item["backend_job_id"])
            except AdapterError as exc:
                self.events.record("cancel", "cancel.failed", exc.message, level="warning", **ictx,
                                   details={"code": exc.code, "backend_job_id": item["backend_job_id"]})
                return {"result": "not_cancelled", "message": exc.message}
            note = "Some pages may already have printed." if status == "processing" else ""
            self._set_item(item["id"], "cancelled", message=("Cancelled. " + note).strip())
            self.events.record("cancel", "cancel.done", "Cancelled in the print system", **ictx,
                               details={"backend_job_id": item["backend_job_id"], "was": status})
            return {"result": "cancelled", "message": note or "Cancelled."}
        explanations = {
            "completed": "Already finished in the print system — too late to cancel.",
            "cancelled": "Already cancelled.",
            "failed": "Did not print, nothing to cancel.",
            "unknown": "Its state is unknown; check the printer directly.",
        }
        return {"result": "not_applicable", "message": explanations.get(status, "Cannot be cancelled.")}

    def retry(self, job_id: str, user: User, confirm_possible_duplicates: bool = False) -> dict:
        job = self._authorize(job_id, user)
        if job["owner_id"] != user.id and not user.is_admin:
            raise JobError(403, "forbidden", "Not allowed.")
        items = self.db.all("SELECT * FROM job_items WHERE job_id = ? ORDER BY position", (job_id,))
        safe = [i for i in items if i["status"] == "failed" and not i["reached_printer"]]
        risky = [i for i in items if i["status"] == "unknown" or (i["status"] == "failed" and i["reached_printer"])]
        chosen = safe + (risky if confirm_possible_duplicates else [])
        if not chosen:
            if risky:
                raise JobError(409, "confirm_duplicates",
                               "These files may already have reached the printer. Check the printer output, then confirm to resend them.",
                               {"positions": [i["position"] for i in risky]})
            raise JobError(409, "nothing_to_retry", "There is nothing to retry: every file was either sent or cancelled.")
        for i in chosen:
            row = self.files.get(i["file_id"])
            if not row or row["status"] != "ready":
                raise JobError(410, "file_gone", "A file needed for the retry has been deleted. Upload it again to print it.")
        with self._item_lock:
            for i in chosen:
                self.db.execute("UPDATE job_items SET status = 'ready', backend_job_id = NULL, message = '', finished_at = NULL,"
                                " reached_printer = 0, stuck_warned = 0, state_reasons = '[]' WHERE id = ?", (i["id"],))
        self.events.record("retry", "retry.requested", f"Retrying {len(chosen)} file(s)", correlation_id=job["correlation_id"],
                           job_id=job_id, printer_id=job["printer_id"], user_id=user.id,
                           details={"positions": [i["position"] for i in chosen], "confirmed_possible_duplicates": bool(risky) and confirm_possible_duplicates,
                                    "skipped_already_sent": [i["position"] for i in items if i not in chosen and i["status"] not in ("failed", "unknown")]})
        self.recompute(job_id)
        self._executor.submit(self._submit_pending, job_id)
        return self.view(job_id, user)

    def reprint(self, job_id: str, user: User, idempotency_key: str) -> tuple[dict, bool]:
        job = self._authorize(job_id, user)
        if job["owner_id"] != user.id:
            raise JobError(403, "forbidden", "Only the person who printed this can reprint it.")
        items = self.db.all("SELECT * FROM job_items WHERE job_id = ? ORDER BY position", (job_id,))
        return self.create(user, {
            "idempotency_key": idempotency_key,
            "printer_id": job["printer_id"],
            "items": [{"file_id": i["file_id"], "page_ranges": i["page_ranges"]} for i in items],
            "settings": loads(job["settings"], {}),
            "preset_name": job["preset_name"],
        }, reprint_of=job_id)

    # ------------------------------------------------------------------ recovery
    def recover_after_restart(self) -> None:
        stuck = self.db.all("SELECT i.*, j.correlation_id FROM job_items i JOIN jobs j ON j.id = i.job_id WHERE i.status IN ('submitting', 'ready')")
        for item in stuck:
            if item["status"] == "submitting":
                self._set_item(item["id"], "unknown", message=(
                    "The hub restarted while this file was being sent. It may or may not have reached the printer — "
                    "check the printer before retrying."))
            else:
                self._set_item(item["id"], "failed", message="The hub restarted before this file was sent. It is safe to retry.")
            self.events.record("service", "item.recovered", "Item state settled after service restart", level="warning",
                               correlation_id=item["correlation_id"], job_id=item["job_id"], item_id=item["id"],
                               details={"was": item["status"]})
        for job_id in {i["job_id"] for i in stuck}:
            self.recompute(job_id)

    # ------------------------------------------------------------------ views
    def view(self, job_id: str, user: User) -> dict:
        job = self._authorize(job_id, user)
        printer = self.db.one("SELECT id, display_name, location, enabled FROM printers WHERE id = ?", (job["printer_id"],))
        owner = self.db.one("SELECT id, username, display_name FROM users WHERE id = ?", (job["owner_id"],))
        items = self.db.all(
            "SELECT i.*, f.original_name, f.kind, f.pages, f.status AS file_status, f.id AS fid FROM job_items i"
            " JOIN files f ON f.id = i.file_id WHERE i.job_id = ? ORDER BY i.position",
            (job_id,),
        )
        own = job["owner_id"] == user.id
        item_views = []
        for i in items:
            item_views.append({
                "id": i["id"],
                "position": i["position"],
                # admins see the queue but not employees' file names
                "name": i["original_name"] if own else f"{i['kind'].upper()} file {i['position'] + 1}",
                "kind": i["kind"],
                "pages": i["pages"],
                "page_ranges": i["page_ranges"],
                "status": i["status"],
                "message": i["message"],
                "reasons": explain_reasons(loads(i["state_reasons"], [])),
                "backend_job_id": i["backend_job_id"],
                "reached_print_system": bool(i["reached_printer"]),
                "attempts": i["attempts"],
                "submitted_at": i["submitted_at"],
                "finished_at": i["finished_at"],
                "file_available": i["file_status"] == "ready",
            })
        counts: dict[str, int] = {}
        for i in item_views:
            counts[i["status"]] = counts.get(i["status"], 0) + 1
        files_ok = all(i["file_available"] for i in item_views)
        return {
            "id": job["id"],
            "reference": job["id"][:6].upper(),
            "correlation_id": job["correlation_id"],
            "status": job["status"],
            "simulated": bool(job["simulated"]),
            "printer": printer,
            "owner": {"id": owner["id"], "display_name": owner["display_name"]} if owner else None,
            "own": own,
            "settings": loads(job["settings"], {}),
            "settings_labels": SETTING_LABELS,
            "settings_display": loads(job["settings_display"], []),
            "preset_name": job["preset_name"],
            "reprint_of": job["reprint_of"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "finished_at": job["finished_at"],
            "items": item_views,
            "counts": counts,
            # true when any file failed or has an uncertain outcome, even while others are still printing
            "attention": any(i["status"] in ("failed", "unknown", "stopped") for i in item_views),
            "can_cancel": any(i["status"] in ("ready", "queued", "held", "processing", "stopped") for i in item_views),
            "can_retry": any(i["status"] in ("failed", "unknown") for i in item_views),
            "can_reprint": own and files_ok and job["status"] not in ("submitting",) and bool(printer and printer["enabled"]),
            "files_retained": files_ok,
        }

    def list(self, user: User, scope: str = "mine", limit: int = 50, status: str | None = None) -> list[dict]:
        sql, params = "SELECT id FROM jobs", []
        clauses = []
        if scope != "all" or not user.is_admin:
            clauses.append("owner_id = ?")
            params.append(user.id)
        if status == "active":
            clauses.append("status IN ('submitting', 'in_progress')")
        elif status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 200)))
        return [self.view(r["id"], user) for r in self.db.all(sql, tuple(params))]

    def timeline(self, job_id: str, user: User) -> list[dict]:
        job = self._authorize(job_id, user)
        rows = self.db.all("SELECT * FROM events WHERE job_id = ? OR (correlation_id = ? AND job_id IS NULL) ORDER BY ts, id",
                           (job_id, job["correlation_id"]))
        out = []
        for r in rows:
            entry = {"ts": r["ts"], "level": r["level"], "category": r["category"], "event": r["event"], "message": r["message"],
                     "item_id": r["item_id"]}
            if user.is_admin:
                entry["details"] = loads(r["details"], {})
            out.append(entry)
        return out

    def purge_history(self, days: int) -> int:
        cutoff = now() - days * 86400
        old = self.db.all("SELECT id FROM jobs WHERE created_at < ? AND status NOT IN ('submitting', 'in_progress')", (cutoff,))
        with self.db.tx() as conn:
            for r in old:
                conn.execute("DELETE FROM job_items WHERE job_id = ?", (r["id"],))
                conn.execute("DELETE FROM jobs WHERE id = ?", (r["id"],))
        return len(old)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
