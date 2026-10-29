import uuid

from conftest import Hub, image_bytes, pdf_bytes

from printhub.printers.base import AdapterError, JobState


def _key():
    return uuid.uuid4().hex


def _job(hub, files, settings=None, key=None, page_ranges=None):
    items = [{"file_id": f, "page_ranges": (page_ranges or {}).get(i)} for i, f in enumerate(files)]
    return hub.client.post("/api/jobs", json={"idempotency_key": key or _key(), "printer_id": "canon",
                                              "items": items, "settings": settings or {}})


def test_happy_path_preserves_order_and_options(hub):
    hub.login("alice")
    a = hub.upload("first.pdf", pdf_bytes(5)).json()["id"]
    b = hub.upload("second.png", image_bytes("PNG")).json()["id"]
    r = _job(hub, [a, b], {"copies": 2, "color_mode": "monochrome", "sides": "two-sided-long-edge"}, page_ranges={0: "2-3"})
    assert r.status_code == 202, r.text
    job = hub.wait_job(r.json()["job"]["id"])
    assert job["status"] == "in_progress"
    assert [i["status"] for i in job["items"]] == ["queued", "queued"]
    subs = hub.state.registry.adapter.submissions
    assert [s["mime"] for s in subs] == ["application/pdf", "image/png"]
    assert subs[0]["options"]["page-ranges"] == "2-3" and "page-ranges" not in subs[1]["options"]
    assert subs[0]["copies"] == 2 and subs[0]["options"]["print-color-mode"] == "monochrome"
    assert "first.pdf" not in subs[0]["title"]  # default titles do not expose file names on the printer panel


def test_duplicate_submission_is_blocked(hub):
    hub.login("alice")
    f = hub.upload("doc.pdf", pdf_bytes(1)).json()["id"]
    key = _key()
    first = _job(hub, [f], key=key)
    second = _job(hub, [f], key=key)
    assert first.status_code == 202 and second.status_code == 200
    assert second.json()["duplicate"] is True
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    hub.wait_job(first.json()["job"]["id"])
    assert len(hub.state.registry.adapter.submissions) == 1


def test_unsupported_settings_send_nothing(hub):
    hub.login("alice")
    f = hub.upload("doc.pdf", pdf_bytes(1)).json()["id"]
    r = _job(hub, [f], {"finishings": ["4"]})
    assert r.status_code == 422
    assert "finishings" in r.json()["details"]["settings"]
    r = _job(hub, [f], page_ranges={0: "1-9"})
    assert r.status_code == 422
    assert hub.state.registry.adapter.submissions == []


def test_partial_failure_and_retry_does_not_duplicate(hub):
    hub.login("alice")
    files = [hub.upload(f"f{i}.pdf", pdf_bytes(1)).json()["id"] for i in range(3)]
    adapter = hub.state.registry.adapter
    adapter.fail_plan = [None, AdapterError("submit_failed", "CUPS rejected the job: printer stopped"), None]
    job = hub.wait_job(_job(hub, files).json()["job"]["id"])
    assert job["status"] == "in_progress" and job["attention"] is True
    assert job["counts"] == {"queued": 2, "failed": 1}
    assert [i["status"] for i in job["items"]] == ["queued", "failed", "queued"]
    assert job["can_retry"]
    r = hub.client.post(f"/api/jobs/{job['id']}/retry", json={})
    assert r.status_code == 200
    job = hub.wait_job(job["id"])
    assert [i["status"] for i in job["items"]] == ["queued", "queued", "queued"]
    assert len(adapter.submissions) == 3  # only the failed file was resent
    timeline = hub.client.get(f"/api/jobs/{job['id']}/timeline").json()["events"]
    assert any(e["event"] == "retry.requested" for e in timeline)


def test_uncertain_submission_requires_confirmation(hub):
    hub.login("alice")
    f = hub.upload("doc.pdf", pdf_bytes(1)).json()["id"]
    hub.state.registry.adapter.fail_plan = [AdapterError("submit_timeout", "Timed out", {"uncertain": True})]
    job = hub.wait_job(_job(hub, [f]).json()["job"]["id"])
    assert job["items"][0]["status"] == "unknown" and job["status"] == "unknown"
    r = hub.client.post(f"/api/jobs/{job['id']}/retry", json={})
    assert r.status_code == 409 and r.json()["error"] == "confirm_duplicates"
    r = hub.client.post(f"/api/jobs/{job['id']}/retry", json={"confirm_possible_duplicates": True})
    assert r.status_code == 200
    assert hub.wait_job(job["id"])["items"][0]["status"] == "queued"


def test_printer_offline_fails_explicitly(hub):
    hub.login("alice")
    f = hub.upload("doc.pdf", pdf_bytes(1)).json()["id"]
    hub.state.registry.adapter.fail_plan = [AdapterError("submit_failed", "CUPS rejected the job: printer offline")]
    job = hub.wait_job(_job(hub, [f]).json()["job"]["id"])
    assert job["status"] == "failed" and "offline" in job["items"][0]["message"]


def test_capabilities_unavailable_blocks_submission(hub):
    hub.login("alice")
    f = hub.upload("doc.pdf", pdf_bytes(1)).json()["id"]
    hub.state.registry.adapter.caps_error = AdapterError("cups_unreachable", "The print system (CUPS) is not responding.")
    r = _job(hub, [f])
    assert r.status_code == 503
    assert hub.state.registry.adapter.submissions == []


def test_tracking_completion_and_lost_jobs(hub):
    hub.login("alice")
    a = hub.upload("a.pdf", pdf_bytes(1)).json()["id"]
    b = hub.upload("b.pdf", pdf_bytes(1)).json()["id"]
    job = hub.wait_job(_job(hub, [a, b]).json()["job"]["id"])
    adapter = hub.state.registry.adapter
    first, second = (i["backend_job_id"] for i in job["items"])
    adapter.states[first] = JobState(state="processing", reasons=["job-printing"])
    hub.state.jobs.poll_once()
    adapter.states[first] = JobState(state="completed", reasons=["job-completed-successfully"])
    adapter.states[second] = None  # CUPS forgot the job
    hub.state.jobs.poll_once()
    job = hub.client.get(f"/api/jobs/{job['id']}").json()["job"]
    assert [i["status"] for i in job["items"]] == ["completed", "unknown"]
    assert job["status"] == "partial"
    events = [e["event"] for e in hub.client.get(f"/api/jobs/{job['id']}/timeline").json()["events"]]
    assert "job.processing" in events and "job.completed" in events and "job.lost" in events


def test_cancel_queued_and_too_late(hub):
    hub.login("alice")
    a = hub.upload("a.pdf", pdf_bytes(1)).json()["id"]
    b = hub.upload("b.pdf", pdf_bytes(1)).json()["id"]
    job = hub.wait_job(_job(hub, [a, b]).json()["job"]["id"])
    adapter = hub.state.registry.adapter
    adapter.states[job["items"][1]["backend_job_id"]] = JobState(state="completed")
    hub.state.jobs.poll_once()
    r = hub.client.post(f"/api/jobs/{job['id']}/cancel")
    body = r.json()["job"]
    assert [c["result"] for c in body["cancel_results"]] == ["cancelled", "not_applicable"]
    assert "too late" in body["cancel_results"][1]["message"]
    assert adapter.cancelled == [job["items"][0]["backend_job_id"]]
    assert body["status"] == "partial"


def test_reprint_requires_retained_files(hub):
    hub.login("alice")
    f = hub.upload("a.pdf", pdf_bytes(1)).json()["id"]
    job = hub.wait_job(_job(hub, [f]).json()["job"]["id"])
    hub.state.registry.adapter.states[job["items"][0]["backend_job_id"]] = JobState(state="completed")
    hub.state.jobs.poll_once()
    r = hub.client.post(f"/api/jobs/{job['id']}/reprint", json={"idempotency_key": _key()})
    assert r.status_code == 202
    assert r.json()["job"]["reprint_of"] == job["id"]
    hub.state.files.delete(hub.state.files.get(f), "test")
    job = hub.client.get(f"/api/jobs/{job['id']}").json()["job"]
    assert job["can_reprint"] is False and job["files_retained"] is False
    r = hub.client.post(f"/api/jobs/{job['id']}/reprint", json={"idempotency_key": _key()})
    assert r.status_code == 422


def test_restart_settles_in_flight_items(tmp_path):
    hub = Hub(tmp_path)
    hub.login("alice")
    f = hub.upload("a.pdf", pdf_bytes(1)).json()["id"]
    job = hub.wait_job(_job(hub, [f]).json()["job"]["id"])
    hub.state.db.execute("UPDATE job_items SET status = 'submitting', backend_job_id = NULL")
    hub.close()
    again = Hub.__new__(Hub)
    from printhub.app import create_app
    from fastapi.testclient import TestClient
    again.app = create_app(hub.config, hub.adapter)
    again.state = again.app.state.hub
    again.client = TestClient(again.app, headers={"X-PrintHub": "1"}, base_url="http://hub.local")
    again.client.__enter__()
    again.login("alice")
    job = again.client.get(f"/api/jobs/{job['id']}").json()["job"]
    assert job["items"][0]["status"] == "unknown"
    assert "restarted" in job["items"][0]["message"]
    events = [e["event"] for e in again.state.diagnostics.search(limit=200)["events"]]
    assert "item.recovered" in events and "service.started" in events
    again.close()


def test_demo_mode_is_simulated_and_separate(tmp_path):
    hub = Hub(tmp_path, mode="demo")
    hub.login("alice")
    printers = hub.client.get("/api/printers").json()
    assert printers["simulated"] is True
    assert all(p["simulated"] for p in printers["printers"])
    f = hub.upload("a.pdf", pdf_bytes(1)).json()["id"]
    r = hub.client.post("/api/jobs", json={"idempotency_key": _key(), "printer_id": "demo-front-mono",
                                           "items": [{"file_id": f}], "settings": {}})
    assert r.status_code == 202, r.text
    job = hub.wait_job(r.json()["job"]["id"])
    assert job["simulated"] is True
    r = hub.client.post("/api/jobs", json={"idempotency_key": _key(), "printer_id": "demo-warehouse",
                                           "items": [{"file_id": f}], "settings": {}})
    assert hub.wait_job(r.json()["job"]["id"])["status"] == "failed"
    hub.close()


def test_production_refuses_simulated_adapter(tmp_path):
    import pytest

    from printhub.app import create_app
    from printhub.config import Config
    from printhub.printers.demo import DemoAdapter

    with pytest.raises(RuntimeError):
        create_app(Config(mode="production", data_dir=tmp_path / "d", log_dir=tmp_path / "l", background_tasks=False), DemoAdapter())
