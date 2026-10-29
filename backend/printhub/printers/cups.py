"""Production adapter: the local CUPS scheduler.

Queries use IPP (structured attributes); submission and cancellation use the
standard `lp`/`cancel` commands so that CUPS applies its normal driver,
filter and option mapping exactly as it would for any desktop application.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .base import (
    JOB_ABORTED, JOB_CANCELLED, JOB_COMPLETED, JOB_HELD, JOB_PENDING, JOB_PROCESSING, JOB_STOPPED,
    AdapterError, JobState, PrinterAdapter, PrinterStatus, QueueInfo, Submission,
)
from .capabilities import normalize_ipp
from .ipp import STATUS_NOT_FOUND, TAG_JOB, TAG_PRINTER, IppClient, IppError, find_cups_socket

IPP_JOB_STATES = {
    3: JOB_PENDING, 4: JOB_HELD, 5: JOB_PROCESSING, 6: JOB_STOPPED, 7: JOB_CANCELLED, 8: JOB_ABORTED, 9: JOB_COMPLETED,
}
OFFLINE_REASONS = ("offline", "offline-report", "timed-out", "shutdown")
STATUS_ATTRS = [
    "printer-state", "printer-state-reasons", "printer-state-message", "printer-is-accepting-jobs",
    "marker-names", "marker-levels", "marker-colors", "marker-types", "marker-low-levels", "marker-high-levels",
    "device-uri", "printer-make-and-model",
]
DEFAULT_PORTS = {"ipp": 631, "ipps": 631, "http": 80, "https": 443, "socket": 9100, "lpd": 515}
_REQUEST_ID_RE = re.compile(r"request id is (?P<queue>.+)-(?P<id>\d+)")


def _reason_base(reason: str) -> str:
    for suffix in ("-error", "-warning", "-report"):
        if reason.endswith(suffix):
            return reason[: -len(suffix)]
    return reason


def parse_markers(attrs: dict[str, list[Any]]) -> list[dict[str, Any]] | None:
    names = attrs.get("marker-names") or []
    levels = attrs.get("marker-levels") or []
    if not names or len(names) != len(levels):
        return None
    colors = attrs.get("marker-colors") or []
    types = attrs.get("marker-types") or []
    lows = attrs.get("marker-low-levels") or []
    out = []
    for i, name in enumerate(names):
        level = levels[i]
        entry = {
            "name": name,
            "type": types[i] if i < len(types) else None,
            "color": colors[i] if i < len(colors) else None,
            "level": level if isinstance(level, int) and level >= 0 else None,
            "low": lows[i] if i < len(lows) and isinstance(lows[i], int) else None,
        }
        if level == -3:
            entry["note"] = "Some remaining (exact level not reported)"
        elif not isinstance(level, int) or level < 0:
            entry["note"] = "Level not reported"
        out.append(entry)
    return out


def interpret_status(attrs: dict[str, list[Any]]) -> PrinterStatus:
    state_num = (attrs.get("printer-state") or [None])[0]
    reasons = [r for r in attrs.get("printer-state-reasons", []) if r and r != "none"]
    accepting = (attrs.get("printer-is-accepting-jobs") or [None])[0]
    bases = {_reason_base(r) for r in reasons}
    if bases & set(OFFLINE_REASONS):
        state = "offline"
    elif state_num == 5 or accepting is False:
        state = "stopped"
    elif any(r.endswith("-error") for r in reasons):
        state = "attention"
    elif state_num == 4:
        state = "busy"
    elif state_num == 3:
        state = "attention" if any(r.endswith("-warning") for r in reasons) else "ready"
    else:
        state = "unknown"
    return PrinterStatus(
        state=state,
        accepting=accepting,
        message=(attrs.get("printer-state-message") or [""])[0] or "",
        reasons=reasons,
        markers=parse_markers(attrs),
        checked_at=time.time(),
    )


def probe_device(device_uri: str, timeout: float = 1.5) -> dict[str, Any]:
    """Best-effort TCP reachability check of the printer behind a CUPS queue."""
    if not device_uri:
        return {"checked": False, "reachable": None, "detail": "No device address is known for this queue."}
    parts = urlsplit(device_uri)
    scheme = parts.scheme.lower()
    if scheme in ("dnssd", "mdns"):
        return {"checked": False, "reachable": None, "detail": "Found by network discovery (Bonjour/mDNS); the hub does not probe it directly."}
    if scheme == "usb":
        return {"checked": False, "reachable": None, "detail": "USB-connected; reachability is reported only by CUPS."}
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        return {"checked": False, "reachable": None, "detail": f"Connection type “{scheme}” is not probed."}
    host, port = parts.hostname, parts.port or DEFAULT_PORTS[scheme]
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ms = round((time.monotonic() - start) * 1000)
            return {"checked": True, "reachable": True, "detail": f"Answered on port {port} in {ms} ms.", "target": f"{host}:{port}"}
    except OSError as exc:
        return {"checked": True, "reachable": False, "detail": f"No answer on port {port}: {exc.strerror or exc}", "target": f"{host}:{port}"}


class CupsAdapter(PrinterAdapter):
    name = "cups"
    simulated = False

    def __init__(self, socket_path: str | None = None, host: str = "localhost", port: int = 631,
                 timeout: float = 5.0, lp_timeout: int = 60, user: str = "printhub"):
        self.client = IppClient(host=host, port=port, timeout=timeout, user=user,
                                socket_path=socket_path or find_cups_socket())
        self.lp_timeout = lp_timeout
        self._env = {**os.environ, "LANG": "C", "LC_ALL": "C"}
        if self.client.socket_path:
            self._env["CUPS_SERVER"] = self.client.socket_path
        elif host:
            self._env["CUPS_SERVER"] = f"{host}:{port}"

    # --- discovery & status ---------------------------------------------
    def list_queues(self) -> list[QueueInfo]:
        try:
            resp = self.client.get_printers(
                ["printer-name", "printer-make-and-model", "printer-location", "printer-info", "device-uri"]
            )
        except IppError as exc:
            raise AdapterError("cups_unreachable", "The print system (CUPS) is not responding.", {"error": str(exc)}) from exc
        out = []
        for attrs in resp.all(TAG_PRINTER):
            name = (attrs.get("printer-name") or [""])[0]
            if not name:
                continue
            out.append(QueueInfo(
                queue_name=name,
                make_model=(attrs.get("printer-make-and-model") or [""])[0] or "",
                location=(attrs.get("printer-location") or [""])[0] or "",
                info=(attrs.get("printer-info") or [""])[0] or "",
                device_uri=(attrs.get("device-uri") or [""])[0] or "",
            ))
        return out

    def _printer_attrs(self, queue: str, requested: list[str] | None) -> dict[str, list[Any]]:
        try:
            resp = self.client.get_printer_attributes(queue, requested)
        except IppError as exc:
            raise AdapterError("cups_unreachable", "The print system (CUPS) is not responding.", {"error": str(exc)}) from exc
        if resp.status == STATUS_NOT_FOUND:
            raise AdapterError("queue_missing", f"The print queue “{queue}” no longer exists in CUPS.")
        if not resp.ok:
            raise AdapterError("ipp_error", "CUPS refused the printer query.", {"ipp_status": hex(resp.status)})
        return resp.first(TAG_PRINTER)

    def status(self, queue: str, probe: bool = False) -> PrinterStatus:
        try:
            attrs = self._printer_attrs(queue, STATUS_ATTRS)
        except AdapterError as exc:
            return PrinterStatus(state="unknown", error=exc.message, checked_at=time.time())
        result = interpret_status(attrs)
        if probe:
            result.reachability = probe_device((attrs.get("device-uri") or [""])[0] or "")
            if result.reachability.get("reachable") is False and result.state in ("ready", "busy", "attention"):
                result.state = "offline"
        return result

    def capabilities(self, queue: str) -> dict[str, Any]:
        return normalize_ipp(self._printer_attrs(queue, None))

    # --- jobs -----------------------------------------------------------
    def submit(self, queue: str, path: Path, mime: str, title: str, options: dict[str, str], copies: int,
               pages: int | None = None) -> Submission:
        cmd = ["lp", "-d", queue, "-t", title[:120], "-n", str(max(1, int(copies)))]
        for key, value in options.items():
            cmd += ["-o", f"{key}={value}"]
        cmd += ["-o", f"document-format={mime}", "--", str(path)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.lp_timeout, env=self._env)
        except FileNotFoundError as exc:
            raise AdapterError("lp_missing", "The `lp` command is not installed (cups-client package).") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(
                "submit_timeout",
                "The print system did not confirm the job in time. It may or may not have been queued — check the queue before retrying.",
                {"timeout_s": self.lp_timeout, "uncertain": True},
            ) from exc
        output = (proc.stdout or "") + (proc.stderr or "")
        match = _REQUEST_ID_RE.search(proc.stdout or "")
        if proc.returncode != 0 or not match:
            raise AdapterError("submit_failed", f"CUPS rejected the job: {output.strip()[:300] or 'no message'}",
                               {"returncode": proc.returncode, "output": output.strip()[:500]})
        return Submission(backend_job_id=match["id"], raw=output.strip()[:300], command=[c for c in cmd if c != str(path)])

    def job_state(self, backend_job_id: str) -> JobState | None:
        try:
            resp = self.client.get_job_attributes(
                int(backend_job_id),
                ["job-state", "job-state-reasons", "job-state-message", "job-printer-state-message", "job-impressions-completed"],
            )
        except IppError as exc:
            raise AdapterError("cups_unreachable", "The print system (CUPS) is not responding.", {"error": str(exc)}) from exc
        if resp.status == STATUS_NOT_FOUND:
            return None
        if not resp.ok:
            raise AdapterError("ipp_error", "CUPS refused the job query.", {"ipp_status": hex(resp.status)})
        attrs = resp.first(TAG_JOB)
        state = IPP_JOB_STATES.get((attrs.get("job-state") or [0])[0])
        if state is None:
            return None
        message = (attrs.get("job-state-message") or [""])[0] or (attrs.get("job-printer-state-message") or [""])[0] or ""
        impressions = (attrs.get("job-impressions-completed") or [None])[0]
        return JobState(
            state=state,
            reasons=[r for r in attrs.get("job-state-reasons", []) if r and r != "none"],
            message=message,
            pages_completed=impressions if isinstance(impressions, int) else None,
        )

    def cancel(self, backend_job_id: str) -> None:
        try:
            proc = subprocess.run(["cancel", str(int(backend_job_id))], capture_output=True, text=True, timeout=20, env=self._env)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise AdapterError("cancel_failed", "The cancel request did not complete.", {"error": str(exc)}) from exc
        if proc.returncode != 0:
            raise AdapterError("cancel_failed", f"CUPS could not cancel the job: {(proc.stderr or proc.stdout).strip()[:200]}")


def queue_device_label(device_uri: str) -> str:
    parts = urlsplit(device_uri or "")
    if parts.scheme in ("dnssd", "mdns"):
        return "Network (discovered): " + unquote(parts.netloc.split("._")[0])
    if parts.scheme == "usb":
        return "USB"
    if parts.hostname:
        return f"{parts.scheme.upper()} · {parts.hostname}"
    return parts.scheme or "Unknown"
