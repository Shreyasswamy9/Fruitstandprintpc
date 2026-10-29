import uuid

from conftest import pdf_bytes


def test_signed_out_requests_are_rejected(hub):
    hub.client.cookies.clear()
    assert hub.client.get("/api/printers").status_code == 401
    assert hub.client.get("/api/jobs").status_code == 401
    assert hub.client.get("/api/bootstrap").status_code == 200


def test_csrf_header_and_origin_required(hub):
    hub.login("alice")
    r = hub.client.post("/api/auth/logout", headers={"X-PrintHub": ""})
    assert r.status_code == 403
    r = hub.client.post("/api/auth/logout", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_employee_cannot_use_admin_endpoints(hub):
    hub.login("alice")
    for path in ("/api/admin/printers", "/api/admin/users", "/api/admin/settings", "/api/admin/diagnostics/events",
                 "/api/admin/diagnostics/report"):
        assert hub.client.get(path).status_code == 403, path
    assert hub.client.patch("/api/admin/settings", json={"station_name": "x"}).status_code == 403
    assert hub.client.patch("/api/admin/printers/canon", json={"enabled": False}).status_code == 403


def test_job_ownership(hub):
    hub.login("alice")
    f = hub.upload("alice-private.pdf", pdf_bytes(1)).json()["id"]
    job_id = hub.client.post("/api/jobs", json={"idempotency_key": uuid.uuid4().hex, "printer_id": "canon",
                                                "items": [{"file_id": f}]}).json()["job"]["id"]
    hub.wait_job(job_id)

    hub.login("bob")
    for path in (f"/api/jobs/{job_id}", f"/api/jobs/{job_id}/timeline"):
        assert hub.client.get(path).status_code == 404
    assert hub.client.post(f"/api/jobs/{job_id}/cancel").status_code == 404
    assert hub.client.post(f"/api/jobs/{job_id}/retry", json={}).status_code == 404
    assert hub.client.get("/api/jobs").json()["jobs"] == []
    assert hub.client.get("/api/jobs?scope=all").json()["jobs"] == []  # scope=all is ignored for employees
    # Bob cannot print Alice's file by guessing its id
    r = hub.client.post("/api/jobs", json={"idempotency_key": uuid.uuid4().hex, "printer_id": "canon", "items": [{"file_id": f}]})
    assert r.status_code == 404

    hub.login("admin")
    jobs = hub.client.get("/api/jobs?scope=all").json()["jobs"]
    assert [j["id"] for j in jobs] == [job_id]
    assert jobs[0]["items"][0]["name"] == "PDF file 1"  # admins don't see employees' file names
    timeline = hub.client.get(f"/api/jobs/{job_id}/timeline").json()["events"]
    assert all("details" in e for e in timeline)
    r = hub.client.post(f"/api/jobs/{job_id}/reprint", json={"idempotency_key": uuid.uuid4().hex})
    assert r.status_code == 403


def test_login_throttle(hub):
    hub.client.cookies.clear()
    for _ in range(5):
        assert hub.client.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"}).status_code == 401
    r = hub.client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass-1"})
    assert r.status_code == 429


def test_forced_password_change(hub):
    hub.login("admin")
    uid = hub.client.post("/api/admin/users", json={"username": "carol", "display_name": "Carol", "password": "temp-pass-1"}).json()["id"]
    hub.client.cookies.clear()
    r = hub.client.post("/api/auth/login", json={"username": "carol", "password": "temp-pass-1"})
    assert r.json()["user"]["must_change_password"] is True
    assert hub.client.get("/api/printers").status_code == 403
    r = hub.client.post("/api/auth/password", json={"current_password": "temp-pass-1", "new_password": "carols-own-pass"})
    assert r.status_code == 200
    assert hub.client.get("/api/printers").status_code == 200
    assert uid


def test_last_admin_cannot_be_removed(hub):
    hub.login("admin")
    r = hub.client.patch(f"/api/admin/users/{hub.ids['admin']}", json={"role": "employee"})
    assert r.status_code == 400


def test_secrets_never_logged(hub):
    hub.client.cookies.clear()
    hub.client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass-1"})
    hub.client.post("/api/auth/login", json={"username": "alice", "password": "a-wrong-guess"})
    log = (hub.state.config.log_dir / "printhub.jsonl").read_text()
    db_events = str(hub.state.db.all("SELECT * FROM events"))
    for secret in ("alice-pass-1", "a-wrong-guess", hub.client.cookies.get("ph_session") or "no-cookie"):
        assert secret not in log and secret not in db_events
