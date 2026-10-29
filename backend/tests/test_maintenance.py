import json
import uuid

from conftest import Hub, pdf_bytes

from printhub.events import redact, setup_logging


def test_cleanup_respects_active_jobs(hub):
    hub.login("alice")
    idle = hub.upload("idle.pdf", pdf_bytes(1)).json()["id"]
    busy = hub.upload("busy.pdf", pdf_bytes(1)).json()["id"]
    job = hub.client.post("/api/jobs", json={"idempotency_key": uuid.uuid4().hex, "printer_id": "canon",
                                             "items": [{"file_id": busy}]}).json()["job"]
    hub.wait_job(job["id"])
    hub.state.db.execute("UPDATE files SET expires_at = 0")
    result = hub.state.run_cleanup()
    assert result["removed"] == 1 and result["kept_for_active_jobs"] == 1
    assert hub.state.files.get(idle)["status"] == "deleted"
    assert hub.state.files.get(busy)["status"] == "ready"


def test_retention_purges_old_history_and_events(hub):
    hub.state.events.record("service", "test.old", "old event")
    hub.state.db.execute("UPDATE events SET ts = 0 WHERE event = 'test.old'")
    hub.state.run_cleanup()
    assert not hub.state.db.one("SELECT 1 FROM events WHERE event = 'test.old'")


def test_log_rotation_is_bounded(tmp_path):
    logger = setup_logging(tmp_path, max_bytes=2000, backups=2)
    for i in range(500):
        logger.info("line %s %s", i, "x" * 50)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["printhub.jsonl", "printhub.jsonl.1", "printhub.jsonl.2"]
    for line in (tmp_path / "printhub.jsonl").read_text().splitlines():
        json.loads(line)


def test_redaction():
    out = redact({"password": "x", "nested": {"session_token": "y", "ok": "fine"}, "long": "z" * 2000})
    assert out["password"] == "[redacted]" and out["nested"]["session_token"] == "[redacted]"
    assert out["nested"]["ok"] == "fine" and len(out["long"]) < 600


def test_support_report_is_redacted(hub):
    hub.login("alice")
    f = hub.upload("Quarterly Salaries.pdf", pdf_bytes(1)).json()["id"]
    hub.client.post("/api/jobs", json={"idempotency_key": uuid.uuid4().hex, "printer_id": "canon", "items": [{"file_id": f}]})
    hub.login("admin")
    r = hub.client.get("/api/admin/diagnostics/report")
    assert r.status_code == 200
    text = r.text
    assert "Quarterly Salaries" not in text and "alice" not in text.lower().replace("alice@", "")
    report = json.loads(text)
    assert report["events"] and report["health"]["checks"]


def test_diagnostics_search(hub):
    hub.login("alice")
    f = hub.upload("x.pdf", pdf_bytes(1)).json()["id"]
    job = hub.client.post("/api/jobs", json={"idempotency_key": uuid.uuid4().hex, "printer_id": "canon",
                                             "items": [{"file_id": f}]}).json()["job"]
    hub.wait_job(job["id"])
    hub.login("admin")
    res = hub.client.get("/api/admin/diagnostics/events", params={"correlation_id": job["correlation_id"]}).json()
    names = [e["event"] for e in res["events"]]
    assert {"job.created", "submission.attempt", "submission.accepted", "capabilities.read"} <= set(names)
    accepted = next(e for e in res["events"] if e["event"] == "submission.accepted")
    assert accepted["details"]["backend_job_id"] and accepted["help"]
    errors = hub.client.get("/api/admin/diagnostics/events", params={"level": "error"}).json()["events"]
    assert all(e["level"] == "error" for e in errors)


def test_test_page_is_tracked_like_a_job(hub):
    hub.login("admin")
    r = hub.client.post("/api/admin/printers/canon/test-page")
    assert r.status_code == 200, r.text
    job = hub.wait_job(r.json()["job"]["id"])
    assert job["preset_name"] == "Test page" and job["items"][0]["status"] == "queued"
    sub = hub.state.registry.adapter.submissions[-1]
    assert sub["mime"] == "application/pdf"


def test_settings_validation(hub):
    hub.login("admin")
    r = hub.client.patch("/api/admin/settings", json={"file_retention_hours": 0})
    assert r.status_code == 400
    r = hub.client.patch("/api/admin/settings", json={"station_name": "LIC Studio", "file_retention_hours": 48})
    assert r.status_code == 200 and r.json()["settings"]["station_name"] == "LIC Studio"
    assert hub.client.get("/api/bootstrap").json()["settings"]["station_name"] == "LIC Studio"
