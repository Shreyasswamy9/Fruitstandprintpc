"""Static service configuration, read from environment variables.

Values that administrators change at runtime (station name, retention,
appearance) live in the database `settings` table instead; see settings.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"PRINTHUB_{name}", default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(f"PRINTHUB_{name}")
    return int(raw) if raw not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(f"PRINTHUB_{name}")
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    # "production" talks to CUPS only. "demo" uses simulated printers only.
    mode: str = "production"
    data_dir: Path = Path("/var/lib/printhub")
    log_dir: Path = Path("/var/log/printhub")
    static_dir: Path | None = None
    host: str = "0.0.0.0"
    port: int = 8080

    # Upload and processing limits
    max_file_mb: int = 50
    max_files_per_job: int = 20
    max_pdf_pages: int = 500
    max_image_megapixels: int = 80
    inspect_timeout_s: int = 30
    inspect_memory_mb: int = 768

    # Sessions
    session_hours: int = 12
    secure_cookies: bool = False
    login_max_failures: int = 5
    login_lockout_minutes: int = 5

    # CUPS
    cups_socket: str | None = None
    cups_host: str = "localhost"
    cups_port: int = 631
    cups_timeout_s: float = 5.0
    lp_timeout_s: int = 60
    service_user: str = "printhub"

    # Background loops
    poll_interval_s: float = 3.0
    status_interval_s: float = 20.0
    cleanup_interval_s: float = 900.0
    stuck_job_minutes: int = 20

    # Log rotation
    log_max_bytes: int = 5 * 1024 * 1024
    log_backups: int = 5

    background_tasks: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def demo(self) -> bool:
        return self.mode == "demo"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "printhub.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Config":
        static = _env("STATIC_DIR", "")
        mode = _env("MODE", "production").strip().lower()
        if mode not in ("production", "demo"):
            raise ValueError(f"PRINTHUB_MODE must be 'production' or 'demo', got {mode!r}")
        return cls(
            mode=mode,
            data_dir=Path(_env("DATA_DIR", "/var/lib/printhub")),
            log_dir=Path(_env("LOG_DIR", "/var/log/printhub")),
            static_dir=Path(static) if static else None,
            host=_env("HOST", "0.0.0.0"),
            port=_env_int("PORT", 8080),
            max_file_mb=_env_int("MAX_FILE_MB", 50),
            max_files_per_job=_env_int("MAX_FILES_PER_JOB", 20),
            max_pdf_pages=_env_int("MAX_PDF_PAGES", 500),
            max_image_megapixels=_env_int("MAX_IMAGE_MEGAPIXELS", 80),
            inspect_timeout_s=_env_int("INSPECT_TIMEOUT_S", 30),
            inspect_memory_mb=_env_int("INSPECT_MEMORY_MB", 768),
            session_hours=_env_int("SESSION_HOURS", 12),
            secure_cookies=_env_bool("SECURE_COOKIES", False),
            cups_socket=_env("CUPS_SOCKET", "") or None,
            cups_host=_env("CUPS_HOST", "localhost"),
            cups_port=_env_int("CUPS_PORT", 631),
            service_user=_env("SERVICE_USER", "printhub"),
            poll_interval_s=float(_env("POLL_INTERVAL_S", "3")),
            stuck_job_minutes=_env_int("STUCK_JOB_MINUTES", 20),
            log_max_bytes=_env_int("LOG_MAX_BYTES", 5 * 1024 * 1024),
            log_backups=_env_int("LOG_BACKUPS", 5),
        )
