from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from printhub.app import create_app
from printhub.config import Config
from printhub.db import now
from printhub.printers.base import (
    JOB_PENDING, AdapterError, JobState, PrinterAdapter, PrinterStatus, QueueInfo, Submission,
)
from printhub.printers.capabilities import normalize_ipp

FIXTURES = Path(__file__).parent / "fixtures"
CANON_ATTRS = json.loads((FIXTURES / "canon_mf750c_ii_attrs.json").read_text())


class FakeCups(PrinterAdapter):
    """Stands in for CUPS in tests. Uses capabilities captured from a real Canon MF750C II."""

    name = "cups"
    simulated = False

    def __init__(self):
        self.queues = {"Canon_MF750C_II_Series": QueueInfo("Canon_MF750C_II_Series", "Canon MF750C II Series", "Studio", "Canon", "ipps://10.0.0.5/ipp/print")}
        self.submissions: list[dict] = []
        self.fail_plan: list[AdapterError | None] = []
        self.states: dict[str, JobState | None] = {}
        self.cancelled: list[str] = []
        self.status_state = "ready"
        self.caps_error: AdapterError | None = None
        self._next = 100

    def list_queues(self):
        return list(self.queues.values())

    def status(self, queue, probe=False):
        return PrinterStatus(state=self.status_state, accepting=True, checked_at=time.time())

    def capabilities(self, queue):
        if self.caps_error:
            raise self.caps_error
        return normalize_ipp(CANON_ATTRS)

    def submit(self, queue, path, mime, title, options, copies, pages=None):
        if self.fail_plan:
            err = self.fail_plan.pop(0)
            if err:
                raise err
        assert Path(path).exists()
        self._next += 1
        job_id = str(self._next)
        self.submissions.append({"queue": queue, "path": str(path), "mime": mime, "title": title,
                                 "options": options, "copies": copies, "id": job_id})
        self.states[job_id] = JobState(state=JOB_PENDING, reasons=["job-queued"])
        return Submission(backend_job_id=job_id, raw=f"request id is {queue}-{job_id}")

    def job_state(self, backend_job_id):
        return self.states.get(backend_job_id)

    def cancel(self, backend_job_id):
        st = self.states.get(backend_job_id)
        if st is None or st.state == "completed":
            raise AdapterError("too_late", "Already finished.")
        self.cancelled.append(backend_job_id)
        self.states[backend_job_id] = JobState(state="cancelled")


def pdf_bytes(pages: int = 3) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(612, 792)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def image_bytes(fmt: str, size=(40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "orange").save(buf, format=fmt)
    return buf.getvalue()


class Hub:
    def __init__(self, tmp_path: Path, adapter: PrinterAdapter | None = None, mode: str = "production", **overrides):
        self.config = Config(mode=mode, data_dir=tmp_path / "data", log_dir=tmp_path / "logs", background_tasks=False,
                             max_file_mb=2, **overrides)
        self.adapter = adapter if adapter is not None else (FakeCups() if mode == "production" else None)
        self.app = create_app(self.config, self.adapter)
        self.state = self.app.state.hub
        self.client = TestClient(self.app, headers={"X-PrintHub": "1"}, base_url="http://hub.local")
        self.client.__enter__()
        a = self.state.accounts
        self.ids = {
            "admin": a.create_user("admin", "Ada Admin", "admin-pass-1", "admin", must_change=False),
            "alice": a.create_user("alice", "Alice Example", "alice-pass-1", "employee", must_change=False),
            "bob": a.create_user("bob", "Bob Example", "bob-pass-12", "employee", must_change=False),
        }
        if mode == "production":
            t = now()
            self.state.db.execute(
                "INSERT INTO printers (id, adapter, queue_name, display_name, location, make_model, device_uri, created_at, updated_at)"
                " VALUES ('canon', 'cups', 'Canon_MF750C_II_Series', 'Studio Canon', 'Studio', 'Canon MF750C II', 'ipps://10.0.0.5/ipp/print', ?, ?)",
                (t, t),
            )

    def login(self, who: str) -> TestClient:
        passwords = {"admin": "admin-pass-1", "alice": "alice-pass-1", "bob": "bob-pass-12"}
        self.client.cookies.clear()
        r = self.client.post("/api/auth/login", json={"username": who, "password": passwords[who]})
        assert r.status_code == 200, r.text
        return self.client

    def upload(self, name: str, data: bytes):
        return self.client.post("/api/files", content=data, headers={"X-Filename": name})

    def wait_job(self, job_id: str, until=lambda j: j["status"] != "submitting", timeout=5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.client.get(f"/api/jobs/{job_id}").json()["job"]
            if until(job):
                return job
            time.sleep(0.05)
        raise AssertionError(f"job did not settle: {job}")

    def close(self):
        self.client.__exit__(None, None, None)


@pytest.fixture
def hub(tmp_path):
    h = Hub(tmp_path)
    yield h
    h.close()
