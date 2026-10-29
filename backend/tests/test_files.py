import io

from pypdf import PdfWriter

from conftest import image_bytes, pdf_bytes


def test_accepts_supported_types(hub):
    hub.login("alice")
    r = hub.upload("report.pdf", pdf_bytes(3))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "pdf" and body["pages"] == 3 and body["width_pt"] == 612
    for name, fmt in (("photo.jpg", "JPEG"), ("chart.png", "PNG")):
        r = hub.upload(name, image_bytes(fmt))
        assert r.status_code == 200, r.text
        assert r.json()["notes"] == []


def test_webp_is_converted_with_explicit_note(hub):
    hub.login("alice")
    r = hub.upload("mood.webp", image_bytes("WEBP"))
    assert r.status_code == 200, r.text
    assert any("WebP" in n for n in r.json()["notes"])
    row = hub.state.files.get(r.json()["id"])
    assert row["print_mime"] == "image/png"
    assert hub.state.files.path_for(row["print_name"]).exists()


def test_rejects_unsupported_extension(hub):
    hub.login("alice")
    r = hub.upload("budget.xlsx", b"PK\x03\x04 not really")
    assert r.status_code == 415
    assert "PDF" in r.json()["message"]


def test_rejects_disguised_content(hub):
    hub.login("alice")
    r = hub.upload("invoice.pdf", b"MZ\x90\x00 this is an executable")
    assert r.status_code == 422
    assert r.json()["error"] == "unsupported_type"
    assert list(hub.state.config.upload_dir.iterdir()) == []


def test_mismatched_extension_is_handled_by_content(hub):
    hub.login("alice")
    r = hub.upload("scan.jpg", image_bytes("PNG"))
    assert r.status_code == 200
    assert r.json()["mime"] == "image/png"
    assert "content is PNG" in r.json()["notes"][0]


def test_rejects_encrypted_pdf(hub):
    hub.login("alice")
    w = PdfWriter()
    w.add_blank_page(612, 792)
    w.encrypt("secret")
    buf = io.BytesIO()
    w.write(buf)
    r = hub.upload("locked.pdf", buf.getvalue())
    assert r.status_code == 422 and r.json()["error"] == "pdf_encrypted"


def test_rejects_oversize_and_empty(hub):
    hub.login("alice")
    r = hub.upload("huge.pdf", b"%PDF-" + b"0" * (3 * 1024 * 1024))
    assert r.status_code == 413
    r = hub.upload("empty.pdf", b"")
    assert r.status_code in (400, 422)
    assert list(hub.state.config.upload_dir.iterdir()) == []


def test_filename_never_becomes_a_path(hub):
    hub.login("alice")
    r = hub.upload("..%2F..%2Fetc%2Fpasswd.pdf", pdf_bytes(1))
    assert r.status_code == 200
    assert r.json()["name"] == "passwd.pdf"
    row = hub.state.files.get(r.json()["id"])
    assert row["storage_name"].endswith(".bin") and "/" not in row["storage_name"]
    stored = list(hub.state.config.upload_dir.iterdir())
    assert len(stored) == 1 and stored[0].parent == hub.state.config.upload_dir


def test_file_privacy(hub):
    hub.login("alice")
    fid = hub.upload("private.pdf", pdf_bytes(1)).json()["id"]
    assert hub.client.get(f"/api/files/{fid}/content").status_code == 200
    hub.login("bob")
    assert hub.client.get(f"/api/files/{fid}/content").status_code == 404
    assert hub.client.delete(f"/api/files/{fid}").status_code == 404
    assert hub.client.get("/api/files").json()["files"] == []
    hub.login("admin")  # administrators cannot open employees' documents
    assert hub.client.get(f"/api/files/{fid}/content").status_code == 404


def test_delete_own_file(hub):
    hub.login("alice")
    fid = hub.upload("a.pdf", pdf_bytes(1)).json()["id"]
    assert hub.client.delete(f"/api/files/{fid}").status_code == 200
    assert hub.client.get("/api/files").json()["files"] == []
    assert list(hub.state.config.upload_dir.iterdir()) == []


def test_interrupted_upload_leaves_nothing_behind(hub):
    """Simulates the network dropping mid-upload."""
    import asyncio

    async def chunks():
        yield b"%PDF-1.4 partial"
        raise ConnectionResetError("client went away")

    async def run():
        await hub.state.files.receive(hub.ids["alice"], "half.pdf", None, chunks(), 24, "c-test")

    try:
        asyncio.run(run())
        raise AssertionError("expected failure")
    except ConnectionResetError:
        pass
    assert list(hub.state.config.upload_dir.iterdir()) == []
    events = [e["event"] for e in hub.state.diagnostics.search(correlation_id="c-test")["events"]]
    assert "upload.rejected" in events


def test_slow_or_hostile_file_is_bounded(hub, monkeypatch):
    hub.state.config.inspect_timeout_s = 1
    import printhub.documents as documents

    real_run = documents.subprocess.run

    def slow(cmd, **kw):
        return real_run(["python3", "-c", "import time; time.sleep(5)"], **{**kw, "preexec_fn": None})

    monkeypatch.setattr(documents.subprocess, "run", slow)
    hub.login("alice")
    r = hub.upload("slow.pdf", pdf_bytes(1))
    assert r.status_code == 422 and r.json()["error"] == "too_slow"
    assert list(hub.state.config.upload_dir.iterdir()) == []
