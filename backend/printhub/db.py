"""SQLite persistence: connection handling and schema migrations."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS: list[str] = [
    # 1 — initial schema
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('employee', 'admin')),
        active INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        last_login_at REAL
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        last_seen_at REAL NOT NULL,
        station INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX sessions_user ON sessions(user_id);

    CREATE TABLE files (
        id TEXT PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id),
        original_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        mime TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        pages INTEGER,
        width_pt REAL,
        height_pt REAL,
        storage_name TEXT NOT NULL,
        print_name TEXT,
        print_mime TEXT,
        notes TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        deleted_at REAL
    );
    CREATE INDEX files_owner ON files(owner_id, status);

    CREATE TABLE printers (
        id TEXT PRIMARY KEY,
        adapter TEXT NOT NULL,
        queue_name TEXT NOT NULL,
        display_name TEXT NOT NULL,
        location TEXT NOT NULL DEFAULT '',
        make_model TEXT NOT NULL DEFAULT '',
        device_uri TEXT NOT NULL DEFAULT '',
        image TEXT NOT NULL DEFAULT 'laser',
        enabled INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        defaults TEXT NOT NULL DEFAULT '{}',
        notes TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE (adapter, queue_name)
    );

    CREATE TABLE presets (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        settings TEXT NOT NULL,
        builtin INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );

    CREATE TABLE jobs (
        id TEXT PRIMARY KEY,
        correlation_id TEXT NOT NULL,
        owner_id INTEGER NOT NULL REFERENCES users(id),
        printer_id TEXT NOT NULL REFERENCES printers(id),
        idempotency_key TEXT NOT NULL,
        status TEXT NOT NULL,
        simulated INTEGER NOT NULL DEFAULT 0,
        settings TEXT NOT NULL,
        preset_name TEXT,
        reprint_of TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        finished_at REAL,
        UNIQUE (owner_id, idempotency_key)
    );
    CREATE INDEX jobs_owner ON jobs(owner_id, created_at);
    CREATE INDEX jobs_status ON jobs(status);

    CREATE TABLE job_items (
        id INTEGER PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        file_id TEXT NOT NULL REFERENCES files(id),
        position INTEGER NOT NULL,
        page_ranges TEXT,
        status TEXT NOT NULL,
        backend_job_id TEXT,
        state_reasons TEXT NOT NULL DEFAULT '[]',
        message TEXT NOT NULL DEFAULT '',
        attempts INTEGER NOT NULL DEFAULT 0,
        reached_printer INTEGER NOT NULL DEFAULT 0,
        submitted_at REAL,
        finished_at REAL,
        last_checked_at REAL,
        stuck_warned INTEGER NOT NULL DEFAULT 0,
        UNIQUE (job_id, position)
    );
    CREATE INDEX job_items_status ON job_items(status);

    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        ts REAL NOT NULL,
        correlation_id TEXT,
        job_id TEXT,
        item_id INTEGER,
        printer_id TEXT,
        user_id INTEGER,
        level TEXT NOT NULL,
        category TEXT NOT NULL,
        event TEXT NOT NULL,
        message TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX events_ts ON events(ts);
    CREATE INDEX events_corr ON events(correlation_id);
    CREATE INDEX events_job ON events(job_id);

    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # 2 — human-readable settings captured from the printer's capabilities at submission time
    """
    ALTER TABLE jobs ADD COLUMN settings_display TEXT NOT NULL DEFAULT '[]';
    """,
]


class Database:
    """Thread-safe wrapper around one SQLite file.

    SQLite serialises writers itself; a process-wide lock keeps our
    multi-statement transactions from interleaving between threads.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=15)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
                self._conn.execute("BEGIN")
                try:
                    for statement in script.split(";"):
                        if statement.strip():
                            self._conn.execute(statement)
                    self._conn.execute(f"PRAGMA user_version={index}")
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise

    @property
    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def backup_to(self, dest: Path) -> None:
        with self._lock:
            target = sqlite3.connect(str(dest))
            try:
                self._conn.backup(target)
            finally:
                target.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def now() -> float:
    return time.time()


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def loads(value: str | None, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)
