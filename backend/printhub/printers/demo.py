"""Simulated printers for demo mode.

Only active when PRINTHUB_MODE=demo. Nothing here touches CUPS, and every
job it reports is marked simulated by the job service — a demo job is never
presented as physical output.
"""
from __future__ import annotations

import itertools
import threading
import time
from pathlib import Path
from typing import Any

from .base import (
    JOB_CANCELLED, JOB_COMPLETED, JOB_PENDING, JOB_PROCESSING,
    AdapterError, JobState, PrinterAdapter, PrinterStatus, QueueInfo, Submission,
)
from .capabilities import normalize_ipp

_LETTER = ["na_letter_8.5x11in", "na_legal_8.5x14in", "iso_a4_210x297mm"]

DEMO_PRINTERS: dict[str, dict[str, Any]] = {
    "demo-studio-color": {
        "info": QueueInfo("demo-studio-color", "Simulated color laser MFP", "Studio · 2nd floor", "Studio Color", "demo://studio-color"),
        "image": "mfp",
        "status": {"state": "ready", "reasons": ["media-low-warning"], "message": "Tray 2 paper low",
                   "markers": [("Black toner", "#000000", 64), ("Cyan toner", "#00FFFF", 41), ("Magenta toner", "#FF00FF", 58), ("Yellow toner", "#FFFF00", 12)]},
        "attrs": {
            "copies-supported": [(1, 999)],
            "print-color-mode-supported": ["color", "monochrome"], "print-color-mode-default": ["color"],
            "sides-supported": ["one-sided", "two-sided-long-edge", "two-sided-short-edge"], "sides-default": ["two-sided-long-edge"],
            "media-supported": _LETTER + ["na_ledger_11x17in"], "media-default": ["na_letter_8.5x11in"],
            "orientation-requested-supported": [3, 4], "page-ranges-supported": [True],
            "print-scaling-supported": ["auto", "fit", "none", "fill"],
            "media-source-supported": ["auto", "tray-1", "tray-2", "by-pass-tray"], "media-source-default": ["auto"],
            "media-type-supported": ["auto", "stationery", "stationery-heavyweight", "cardstock"],
            "print-quality-supported": [3, 4, 5], "print-quality-default": [4],
            "multiple-document-handling-supported": ["separate-documents-uncollated-copies", "separate-documents-collated-copies"],
            "finishings-supported": [3, 4, 20, 74],
            "document-format-supported": ["application/pdf", "image/jpeg", "image/png"],
        },
    },
    "demo-front-mono": {
        "info": QueueInfo("demo-front-mono", "Simulated monochrome laser", "Front desk", "Front Desk Mono", "demo://front-mono"),
        "image": "laser",
        "status": {"state": "ready", "reasons": [], "message": "",
                   "markers": [("Black toner", "#000000", 18)]},
        "attrs": {
            "copies-supported": [(1, 999)],
            "print-color-mode-supported": ["monochrome"], "print-color-mode-default": ["monochrome"],
            "sides-supported": ["one-sided", "two-sided-long-edge", "two-sided-short-edge"], "sides-default": ["one-sided"],
            "media-supported": _LETTER, "media-default": ["na_letter_8.5x11in"],
            "orientation-requested-supported": [3, 4], "page-ranges-supported": [True],
            "print-scaling-supported": ["auto", "fit", "none"],
            "media-source-supported": ["auto", "tray-1"],
            "print-quality-supported": [3, 4], "print-quality-default": [4],
            "multiple-document-handling-supported": ["separate-documents-uncollated-copies", "separate-documents-collated-copies"],
            "document-format-supported": ["application/pdf", "image/jpeg", "image/png"],
        },
    },
    "demo-design-photo": {
        "info": QueueInfo("demo-design-photo", "Simulated photo inkjet", "Design room", "Design Photo", "demo://design-photo"),
        "image": "inkjet",
        "status": {"state": "ready", "reasons": [], "message": "", "markers": None},
        "attrs": {
            "copies-supported": [(1, 99)],
            "print-color-mode-supported": ["color", "monochrome"], "print-color-mode-default": ["color"],
            "sides-supported": ["one-sided"],
            "media-supported": ["na_letter_8.5x11in", "na_index-4x6_4x6in", "na_5x7_5x7in"], "media-default": ["na_letter_8.5x11in"],
            "orientation-requested-supported": [3, 4], "page-ranges-supported": [True],
            "print-scaling-supported": ["fit", "fill", "none"],
            "media-type-supported": ["stationery", "photographic-glossy", "photographic-matte"],
            "print-quality-supported": [4, 5],
            "document-format-supported": ["application/pdf", "image/jpeg", "image/png"],
        },
    },
    "demo-warehouse": {
        "info": QueueInfo("demo-warehouse", "Simulated monochrome laser", "Warehouse", "Warehouse", "demo://warehouse"),
        "image": "laser",
        "status": {"state": "offline", "reasons": ["offline-report"], "message": "Printer is not responding", "markers": None},
        "attrs": {
            "copies-supported": [(1, 999)],
            "print-color-mode-supported": ["monochrome"],
            "sides-supported": ["one-sided"],
            "media-supported": ["na_letter_8.5x11in"],
            "document-format-supported": ["application/pdf", "image/jpeg", "image/png"],
        },
    },
    "demo-shipping": {
        "info": QueueInfo("demo-shipping", "Model not yet identified", "Shipping desk", "Shipping Desk", "demo://shipping"),
        "image": "unknown",
        "status": {"state": "unknown"},
        "attrs": None,
    },
}


class DemoAdapter(PrinterAdapter):
    name = "demo"
    simulated = True

    QUEUE_S = 2.5
    PER_PAGE_S = 1.2

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._ids = itertools.count(1001)
        self._lock = threading.Lock()

    def list_queues(self) -> list[QueueInfo]:
        return [p["info"] for p in DEMO_PRINTERS.values()]

    def image_for(self, queue: str) -> str:
        return DEMO_PRINTERS.get(queue, {}).get("image", "laser")

    def status(self, queue: str, probe: bool = False) -> PrinterStatus:
        spec = DEMO_PRINTERS.get(queue)
        if not spec or spec["status"]["state"] == "unknown":
            return PrinterStatus(state="unknown", error="Simulated: this printer does not answer status queries.", checked_at=time.time())
        s = spec["status"]
        state = s["state"]
        busy = any(j["queue"] == queue and self._state_of(j) == JOB_PROCESSING for j in self._jobs.values())
        if busy and state == "ready":
            state = "busy"
        if state == "ready" and any(r.endswith("-warning") for r in s["reasons"]):
            state = "attention"
        markers = None
        if s.get("markers"):
            markers = [
                {"name": n, "type": "toner", "color": c, "level": lvl, "low": 15} for n, c, lvl in s["markers"]
            ]
        return PrinterStatus(
            state=state, accepting=state != "offline", message=s["message"], reasons=list(s["reasons"]), markers=markers,
            reachability={"checked": False, "reachable": None, "detail": "Simulated printer — no network check."} if probe else None,
            checked_at=time.time(),
        )

    def capabilities(self, queue: str) -> dict[str, Any]:
        spec = DEMO_PRINTERS.get(queue)
        if not spec or spec["attrs"] is None:
            raise AdapterError("capabilities_unavailable", "Simulated: this printer did not report its capabilities.")
        caps = normalize_ipp(spec["attrs"])
        caps["source"] = "simulated"
        return caps

    def submit(self, queue: str, path: Path, mime: str, title: str, options: dict[str, str], copies: int,
               pages: int | None = None) -> Submission:
        spec = DEMO_PRINTERS.get(queue)
        if not spec:
            raise AdapterError("queue_missing", "Unknown simulated printer.")
        if spec["status"]["state"] in ("offline", "unknown"):
            raise AdapterError("submit_failed", "Simulated failure: the printer is offline and the job was not accepted.")
        if not path.exists():
            raise AdapterError("file_missing", "The prepared file is missing.")
        pages = max(1, pages or 1)
        with self._lock:
            job_id = str(next(self._ids))
            self._jobs[job_id] = {"queue": queue, "start": time.time(), "pages": pages * max(1, copies), "cancelled": False}
        return Submission(backend_job_id=job_id, raw=f"simulated request id is {queue}-{job_id}")

    def _state_of(self, job: dict[str, Any]) -> str:
        if job["cancelled"]:
            return JOB_CANCELLED
        elapsed = time.time() - job["start"]
        if elapsed < self.QUEUE_S:
            return JOB_PENDING
        if elapsed < self.QUEUE_S + min(job["pages"], 15) * self.PER_PAGE_S:
            return JOB_PROCESSING
        return JOB_COMPLETED

    def job_state(self, backend_job_id: str) -> JobState | None:
        job = self._jobs.get(backend_job_id)
        if job is None:
            return None  # e.g. after a service restart the simulation forgets its jobs
        state = self._state_of(job)
        done = None
        if state == JOB_PROCESSING:
            done = min(job["pages"], int((time.time() - job["start"] - self.QUEUE_S) / self.PER_PAGE_S))
        reasons = {JOB_PENDING: ["job-queued"], JOB_PROCESSING: ["job-printing"],
                   JOB_COMPLETED: ["job-completed-successfully"], JOB_CANCELLED: ["job-canceled-by-user"]}[state]
        return JobState(state=state, reasons=reasons, message="Simulated", pages_completed=done)

    def cancel(self, backend_job_id: str) -> None:
        job = self._jobs.get(backend_job_id)
        if job is None:
            raise AdapterError("job_missing", "The simulated job is no longer known.")
        if self._state_of(job) == JOB_COMPLETED:
            raise AdapterError("too_late", "The simulated job already finished.")
        job["cancelled"] = True
