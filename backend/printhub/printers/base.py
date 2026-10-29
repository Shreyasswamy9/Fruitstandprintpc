"""Printer adapter interface.

The rest of the application talks to printers only through this interface.
`CupsAdapter` is the production implementation; `DemoAdapter` simulates
printers for development and is never used in production mode.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Normalised job states shared by all adapters.
JOB_PENDING = "queued"
JOB_HELD = "held"
JOB_PROCESSING = "processing"
JOB_STOPPED = "stopped"
JOB_CANCELLED = "cancelled"
JOB_ABORTED = "aborted"
JOB_COMPLETED = "completed"
TERMINAL_JOB_STATES = (JOB_CANCELLED, JOB_ABORTED, JOB_COMPLETED)


class AdapterError(Exception):
    """A printer operation failed. `code` is stable; `message` is human-readable."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class QueueInfo:
    queue_name: str
    make_model: str = ""
    location: str = ""
    info: str = ""
    device_uri: str = ""


@dataclass
class PrinterStatus:
    # ready | busy | attention | stopped | offline | unknown
    state: str
    accepting: bool | None = None
    message: str = ""
    reasons: list[str] = field(default_factory=list)
    markers: list[dict[str, Any]] | None = None
    reachability: dict[str, Any] | None = None
    checked_at: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobState:
    state: str
    reasons: list[str] = field(default_factory=list)
    message: str = ""
    pages_completed: int | None = None


@dataclass
class Submission:
    backend_job_id: str
    raw: str = ""
    command: list[str] = field(default_factory=list)


class PrinterAdapter(ABC):
    name: str = "base"
    simulated: bool = False

    @abstractmethod
    def list_queues(self) -> list[QueueInfo]: ...

    @abstractmethod
    def status(self, queue: str, probe: bool = False) -> PrinterStatus: ...

    @abstractmethod
    def capabilities(self, queue: str) -> dict[str, Any]: ...

    @abstractmethod
    def submit(self, queue: str, path: Path, mime: str, title: str, options: dict[str, str], copies: int,
               pages: int | None = None) -> Submission: ...

    @abstractmethod
    def job_state(self, backend_job_id: str) -> JobState | None:
        """Return the job's state, or None if the print system no longer knows it."""

    @abstractmethod
    def cancel(self, backend_job_id: str) -> None: ...
