"""Configured printers: registration, cached status and capabilities."""
from __future__ import annotations

import re
import secrets
import threading
import time
from typing import Any

from .db import Database, dumps, loads, now
from .events import EventLog
from .printers.base import AdapterError, PrinterAdapter, PrinterStatus
from .printers.cups import queue_device_label
from .printers.explain import explain_reasons

CAPS_TTL_S = 300
IMAGES = ("laser", "mfp", "inkjet", "label", "plotter", "unknown")
STATE_LABELS = {
    "ready": "Ready",
    "busy": "Printing",
    "attention": "Needs attention",
    "stopped": "Paused",
    "offline": "Offline",
    "unknown": "Status unknown",
    "disabled": "Disabled",
}


class PrinterNotFound(Exception):
    pass


class PrinterRegistry:
    def __init__(self, db: Database, events: EventLog, adapter: PrinterAdapter):
        self.db = db
        self.events = events
        self.adapter = adapter
        self._status: dict[str, PrinterStatus] = {}
        self._caps: dict[str, tuple[float, dict[str, Any]]] = {}
        self._caps_errors: dict[str, str] = {}
        self._lock = threading.Lock()

    # --- configuration ----------------------------------------------------
    def sync_demo(self) -> None:
        """In demo mode, make sure the simulated printers are registered."""
        if not self.adapter.simulated:
            return
        for index, queue in enumerate(self.adapter.list_queues()):
            if self.db.one("SELECT 1 FROM printers WHERE adapter = 'demo' AND queue_name = ?", (queue.queue_name,)):
                continue
            t = now()
            self.db.execute(
                "INSERT INTO printers (id, adapter, queue_name, display_name, location, make_model, device_uri, image, sort_order, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (queue.queue_name, "demo", queue.queue_name, queue.info, queue.location, queue.make_model,
                 queue.device_uri, self.adapter.image_for(queue.queue_name), index, t, t),
            )

    def rows(self, include_disabled: bool = False) -> list[dict]:
        sql = "SELECT * FROM printers WHERE adapter = ?"
        if not include_disabled:
            sql += " AND enabled = 1"
        return self.db.all(sql + " ORDER BY sort_order, display_name", (self.adapter.name,))

    def row(self, printer_id: str) -> dict:
        row = self.db.one("SELECT * FROM printers WHERE id = ? AND adapter = ?", (printer_id, self.adapter.name))
        if not row:
            raise PrinterNotFound(printer_id)
        return row

    def discover(self) -> list[dict]:
        known = {r["queue_name"] for r in self.rows(include_disabled=True)}
        out = []
        for q in self.adapter.list_queues():
            out.append({
                "queue_name": q.queue_name, "make_model": q.make_model, "location": q.location, "info": q.info,
                "connection": queue_device_label(q.device_uri), "registered": q.queue_name in known,
            })
        return out

    def register(self, queue_name: str, display_name: str, location: str, image: str, user_id: int) -> dict:
        queues = {q.queue_name: q for q in self.adapter.list_queues()}
        if queue_name not in queues:
            raise ValueError("That print queue does not exist in CUPS.")
        if self.db.one("SELECT 1 FROM printers WHERE adapter = ? AND queue_name = ?", (self.adapter.name, queue_name)):
            raise ValueError("That print queue is already connected.")
        q = queues[queue_name]
        slug = re.sub(r"[^a-z0-9]+", "-", queue_name.lower()).strip("-")[:40] or "printer"
        printer_id = f"{slug}-{secrets.token_hex(2)}"
        t = now()
        self.db.execute(
            "INSERT INTO printers (id, adapter, queue_name, display_name, location, make_model, device_uri, image, sort_order, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,(SELECT COALESCE(MAX(sort_order),0)+1 FROM printers),?,?)",
            (printer_id, self.adapter.name, queue_name, display_name.strip() or q.info or queue_name,
             location.strip() or q.location, q.make_model, q.device_uri, image if image in IMAGES else "laser", t, t),
        )
        self.events.record("admin", "printer.registered", "Printer connected to the hub", printer_id=printer_id,
                           user_id=user_id, details={"queue": queue_name, "make_model": q.make_model})
        return self.row(printer_id)

    def update(self, printer_id: str, changes: dict[str, Any], user_id: int) -> dict:
        row = self.row(printer_id)
        allowed = {"display_name", "location", "image", "enabled", "sort_order", "defaults", "notes"}
        fields = {k: v for k, v in changes.items() if k in allowed and v is not None}
        if "image" in fields and fields["image"] not in IMAGES:
            raise ValueError("Unknown illustration")
        if "display_name" in fields and not str(fields["display_name"]).strip():
            raise ValueError("Name cannot be empty")
        if "defaults" in fields:
            from .printers.capabilities import validate_settings

            clean, errors = validate_settings(fields["defaults"], self.capabilities(printer_id))
            if errors:
                raise ValueError("Defaults not supported by this printer: " + "; ".join(errors.values()))
            fields["defaults"] = dumps(clean)
        if "enabled" in fields:
            fields["enabled"] = int(bool(fields["enabled"]))
        if not fields:
            return row
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE printers SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), now(), printer_id))
        self.events.record("admin", "printer.updated", "Printer settings changed", printer_id=printer_id, user_id=user_id,
                           details={"fields": sorted(fields)})
        return self.row(printer_id)

    def remove(self, printer_id: str, user_id: int) -> None:
        self.row(printer_id)
        in_use = self.db.one("SELECT 1 FROM jobs WHERE printer_id = ? LIMIT 1", (printer_id,))
        if in_use:
            # Keep history intact: disconnecting a printer with jobs only disables it.
            self.update(printer_id, {"enabled": False}, user_id)
            return
        self.db.execute("DELETE FROM printers WHERE id = ?", (printer_id,))
        self.events.record("admin", "printer.removed", "Printer disconnected from the hub", printer_id=printer_id, user_id=user_id)

    # --- live data -----------------------------------------------------------
    def refresh_status(self, printer_id: str | None = None, probe: bool = True) -> None:
        rows = [self.row(printer_id)] if printer_id else self.rows(include_disabled=True)
        for row in rows:
            new = self.adapter.status(row["queue_name"], probe=probe)
            with self._lock:
                old = self._status.get(row["id"])
                self._status[row["id"]] = new
            if old is None or old.state != new.state or set(old.reasons) != set(new.reasons):
                level = "info" if new.state in ("ready", "busy") else "warning"
                self.events.record(
                    "printer", "printer.status", f"{row['display_name']}: {STATE_LABELS.get(new.state, new.state)}",
                    level=level, printer_id=row["id"],
                    details={"state": new.state, "previous": old.state if old else None, "reasons": new.reasons,
                             "message": new.message, "error": new.error, "reachability": new.reachability},
                )

    def status(self, printer_id: str) -> PrinterStatus | None:
        with self._lock:
            return self._status.get(printer_id)

    def capabilities(self, printer_id: str, refresh: bool = False, correlation_id: str | None = None) -> dict[str, Any]:
        row = self.row(printer_id)
        cached = self._caps.get(printer_id)
        if cached and not refresh and time.time() - cached[0] < CAPS_TTL_S:
            return cached[1]
        try:
            caps = self.adapter.capabilities(row["queue_name"])
        except AdapterError as exc:
            self._caps_errors[printer_id] = exc.message
            self.events.record("capability", "capabilities.failed", "Could not read printer capabilities", level="warning",
                               printer_id=printer_id, correlation_id=correlation_id, details={"code": exc.code, "error": exc.message, **exc.details})
            raise
        self._caps[printer_id] = (time.time(), caps)
        self._caps_errors.pop(printer_id, None)
        self.events.record(
            "capability", "capabilities.read", "Printer capabilities read", level="debug" if not correlation_id else "info",
            printer_id=printer_id, correlation_id=correlation_id,
            details={"source": caps.get("source"), "color_modes": [c["key"] for c in caps["color_modes"]],
                     "sides": [s["key"] for s in caps["sides"]], "media": len(caps["media"]),
                     "finishings": [f["key"] for f in caps["finishings"]]},
        )
        return caps

    def public(self, row: dict, admin: bool = False) -> dict[str, Any]:
        st = self.status(row["id"])
        caps_entry = self._caps.get(row["id"])
        caps = caps_entry[1] if caps_entry else None
        state = "disabled" if not row["enabled"] else (st.state if st else "unknown")
        status = {
            "state": state,
            "label": STATE_LABELS.get(state, state),
            "message": st.message if st else "",
            "reasons": explain_reasons(st.reasons) if st else [],
            "markers": st.markers if st else None,
            "reachability": st.reachability if st else None,
            "checked_at": st.checked_at if st else None,
            "error": (st.error if st else "Status has not been checked yet."),
        }
        summary = None
        if caps:
            summary = {
                "color": any(c["key"] == "color" for c in caps["color_modes"]),
                "duplex": any(s["key"] != "one-sided" for s in caps["sides"]),
                "media": [m["label"] for m in caps["media"][:6]],
                "finishing": [f["label"] for f in caps["finishings"]],
                "max_copies": caps["copies"]["max"] if caps.get("copies") else None,
            }
        out = {
            "id": row["id"],
            "display_name": row["display_name"],
            "location": row["location"],
            "make_model": row["make_model"],
            "image": row["image"],
            "enabled": bool(row["enabled"]),
            "simulated": self.adapter.simulated,
            "status": status,
            "capability_summary": summary,
            "capabilities_error": self._caps_errors.get(row["id"]),
            "defaults": loads(row["defaults"], {}),
        }
        if admin:
            out.update({"queue_name": row["queue_name"], "connection": queue_device_label(row["device_uri"]),
                        "device_uri": row["device_uri"], "notes": row["notes"], "sort_order": row["sort_order"]})
        return out

    def warm_capabilities(self) -> None:
        for row in self.rows():
            try:
                self.capabilities(row["id"])
            except AdapterError:
                pass
