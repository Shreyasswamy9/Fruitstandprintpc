"""Structured diagnostic events.

Every event is written to two places:
  * the `events` table (searchable from the admin diagnostics screen), and
  * a rotating JSON-lines file (`<log_dir>/printhub.jsonl`) for support tooling.

Events must never contain passwords, session tokens, or document contents.
`redact()` is applied to every details payload as a second line of defence.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import re
import secrets
import time
from pathlib import Path
from typing import Any

from .db import Database, dumps

SENSITIVE_KEYS = re.compile(r"pass(word)?|secret|token|cookie|authorization|session|credential", re.I)
MAX_STRING = 500

LEVELS = ("debug", "info", "warning", "error")
CATEGORIES = (
    "auth",
    "upload",
    "validation",
    "preparation",
    "capability",
    "submission",
    "job_state",
    "printer",
    "cancel",
    "retry",
    "timeout",
    "admin",
    "service",
    "cleanup",
)


def new_correlation_id() -> str:
    return "c-" + secrets.token_hex(6)


def redact(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if SENSITIVE_KEYS.search(str(key)):
                out[key] = "[redacted]"
            else:
                out[key] = redact(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in list(value)[:100]]
    if isinstance(value, str) and len(value) > MAX_STRING:
        return value[:MAX_STRING] + "…"
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return value


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "payload", None)
        if payload is None:
            payload = {
                "ts": round(record.created, 3),
                "level": record.levelname.lower(),
                "category": "service",
                "event": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["details"] = {"exception": self.formatException(record.exc_info)[-2000:]}
        return json.dumps(payload, separators=(",", ":"), default=str)


def setup_logging(log_dir: Path, max_bytes: int, backups: int) -> logging.Logger:
    """Configure the bounded, rotating JSON log. Returns the event logger."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("printhub")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "printhub.jsonl", maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(_JsonFormatter())
    stream.setLevel(logging.WARNING)
    logger.addHandler(stream)
    return logger


class EventLog:
    def __init__(self, db: Database, logger: logging.Logger | None = None):
        self.db = db
        self.logger = logger or logging.getLogger("printhub")

    def record(
        self,
        category: str,
        event: str,
        message: str,
        *,
        level: str = "info",
        correlation_id: str | None = None,
        job_id: str | None = None,
        item_id: int | None = None,
        printer_id: str | None = None,
        user_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        assert level in LEVELS, level
        assert category in CATEGORIES, category
        ts = time.time()
        clean = redact(details or {})
        try:
            self.db.execute(
                "INSERT INTO events (ts, correlation_id, job_id, item_id, printer_id, user_id, level, category, event, message, details)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ts, correlation_id, job_id, item_id, printer_id, user_id, level, category, event, message, dumps(clean)),
            )
        except Exception:  # never let diagnostics break the request path
            self.logger.exception("failed to store event %s", event)
        payload = {
            "ts": round(ts, 3),
            "level": level,
            "category": category,
            "event": event,
            "message": message,
            "correlation_id": correlation_id,
            "job_id": job_id,
            "item_id": item_id,
            "printer_id": printer_id,
            "user_id": user_id,
            "details": clean,
        }
        self.logger.log(
            {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}[level],
            message,
            extra={"payload": {k: v for k, v in payload.items() if v not in (None, {})}},
        )
