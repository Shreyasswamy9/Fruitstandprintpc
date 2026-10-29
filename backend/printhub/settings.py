"""Administrator-editable runtime settings stored in SQLite."""
from __future__ import annotations

from typing import Any

from .db import Database, dumps, loads

# key -> (default, validator description, validator)
_SPEC: dict[str, tuple[Any, Any]] = {
    "station_name": ("Fruitstand Print Hub", lambda v: isinstance(v, str) and 1 <= len(v.strip()) <= 60),
    "station_subtitle": ("Long Island City", lambda v: isinstance(v, str) and len(v) <= 80),
    "file_retention_hours": (24, lambda v: isinstance(v, int) and 1 <= v <= 24 * 30),
    "history_retention_days": (90, lambda v: isinstance(v, int) and 1 <= v <= 3650),
    "event_retention_days": (30, lambda v: isinstance(v, int) and 1 <= v <= 365),
    "station_idle_logout_minutes": (3, lambda v: isinstance(v, int) and 1 <= v <= 120),
    "job_title_style": ("reference", lambda v: v in ("reference", "filename")),
    "appearance_theme": ("system", lambda v: v in ("system", "light", "dark")),
    "appearance_motion": ("full", lambda v: v in ("full", "reduced")),
    "appearance_density": ("comfortable", lambda v: v in ("comfortable", "compact")),
}

PUBLIC_KEYS = (
    "station_name",
    "station_subtitle",
    "appearance_theme",
    "appearance_motion",
    "appearance_density",
    "station_idle_logout_minutes",
    "file_retention_hours",
)


class SettingsError(ValueError):
    pass


class Settings:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> Any:
        default, _ = _SPEC[key]
        row = self.db.one("SELECT value FROM settings WHERE key = ?", (key,))
        return loads(row["value"]) if row else default

    def all(self) -> dict[str, Any]:
        stored = {r["key"]: loads(r["value"]) for r in self.db.all("SELECT key, value FROM settings")}
        return {key: stored.get(key, default) for key, (default, _) in _SPEC.items()}

    def public(self) -> dict[str, Any]:
        values = self.all()
        return {k: values[k] for k in PUBLIC_KEYS}

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        errors = {}
        for key, value in changes.items():
            if key not in _SPEC:
                errors[key] = "Unknown setting"
            elif not _SPEC[key][1](value):
                errors[key] = "Invalid value"
        if errors:
            raise SettingsError(errors)
        with self.db.tx() as conn:
            for key, value in changes.items():
                if isinstance(value, str):
                    value = value.strip()
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, dumps(value)),
                )
        return self.all()
