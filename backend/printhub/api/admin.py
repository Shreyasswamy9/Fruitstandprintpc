from __future__ import annotations

import json
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..app import AppState, hub
from ..db import dumps, loads, now
from ..events import new_correlation_id
from ..printers.capabilities import SETTING_KEYS
from ..security import User
from ..settings import SettingsError
from ..testpage import render_test_page
from .deps import admin_user

router = APIRouter(prefix="/api/admin")


# --- printers -----------------------------------------------------------------
class RegisterBody(BaseModel):
    queue_name: str = Field(max_length=128)
    display_name: str = Field(default="", max_length=60)
    location: str = Field(default="", max_length=80)
    image: str = "laser"


class PrinterPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=80)
    image: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    defaults: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=1000)


def _bad(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": "invalid", "message": message}, status_code=status)


@router.get("/printers")
def printers(admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    try:
        discovered = state.registry.discover()
        discover_error = None
    except Exception as exc:
        discovered, discover_error = [], getattr(exc, "message", str(exc))
    return {
        "simulated": state.registry.adapter.simulated,
        "printers": [state.registry.public(r, admin=True) for r in state.registry.rows(include_disabled=True)],
        "queues": discovered,
        "discover_error": discover_error,
    }


@router.post("/printers")
def register(body: RegisterBody, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    if state.registry.adapter.simulated:
        return _bad("Demo mode uses fixed simulated printers.")
    try:
        row = state.registry.register(body.queue_name, body.display_name, body.location, body.image, admin.id)
    except ValueError as exc:
        return _bad(str(exc))
    state.registry.refresh_status(row["id"])
    return state.registry.public(row, admin=True)


@router.patch("/printers/{printer_id}")
def update_printer(printer_id: str, body: PrinterPatch, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    try:
        row = state.registry.update(printer_id, body.model_dump(exclude_none=True), admin.id)
    except ValueError as exc:
        return _bad(str(exc))
    return state.registry.public(row, admin=True)


@router.delete("/printers/{printer_id}")
def remove_printer(printer_id: str, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    state.registry.remove(printer_id, admin.id)
    return {"ok": True}


@router.post("/printers/{printer_id}/refresh")
def refresh_printer(printer_id: str, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    state.registry.refresh_status(printer_id, probe=True)
    error = None
    try:
        state.registry.capabilities(printer_id, refresh=True, correlation_id=new_correlation_id())
    except Exception as exc:
        error = getattr(exc, "message", str(exc))
    out = state.registry.public(state.registry.row(printer_id), admin=True)
    out["refresh_error"] = error
    return out


@router.post("/printers/{printer_id}/test-page")
def test_page(printer_id: str, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    row = state.registry.row(printer_id)
    reference = secrets.token_hex(3).upper()
    logo = state.config.static_dir / "brand" / "wordmark.png" if state.config.static_dir else None
    file_row = state.files.add_generated_pdf(
        admin.id, f"Test page · {row['display_name']}",
        lambda p: render_test_page(p, state.settings.get("station_name"), f"{row['display_name']} ({row['queue_name']})", reference, logo),
        retention_hours=24,
    )
    job, _ = state.jobs.create(admin, {
        "idempotency_key": f"testpage-{reference}-{secrets.token_hex(4)}",
        "printer_id": printer_id,
        "items": [{"file_id": file_row["id"]}],
        "settings": {},
        "preset_name": "Test page",
    })
    return {"job": job}


# --- presets ------------------------------------------------------------------
class PresetBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    settings: dict[str, Any]


def _check_preset_settings(settings: dict[str, Any]) -> str | None:
    unknown = [k for k in settings if k not in SETTING_KEYS]
    return f"Unknown setting(s): {', '.join(unknown)}" if unknown else None


@router.post("/presets")
def create_preset(body: PresetBody, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    if err := _check_preset_settings(body.settings):
        return _bad(err)
    t = now()
    cur = state.db.execute(
        "INSERT INTO presets (name, description, settings, sort_order, created_at, updated_at)"
        " VALUES (?,?,?,(SELECT COALESCE(MAX(sort_order),0)+1 FROM presets),?,?)",
        (body.name.strip(), body.description.strip(), dumps(body.settings), t, t),
    )
    state.events.record("admin", "preset.created", "Preset created", user_id=admin.id, details={"preset_id": cur.lastrowid})
    return {"id": cur.lastrowid}


@router.patch("/presets/{preset_id}")
def update_preset(preset_id: int, body: PresetBody, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    if err := _check_preset_settings(body.settings):
        return _bad(err)
    n = state.db.execute("UPDATE presets SET name = ?, description = ?, settings = ?, updated_at = ? WHERE id = ?",
                         (body.name.strip(), body.description.strip(), dumps(body.settings), now(), preset_id)).rowcount
    if not n:
        return _bad("Preset not found.", 404)
    state.events.record("admin", "preset.updated", "Preset changed", user_id=admin.id, details={"preset_id": preset_id})
    return {"ok": True}


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    state.db.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
    state.events.record("admin", "preset.deleted", "Preset deleted", user_id=admin.id, details={"preset_id": preset_id})
    return {"ok": True}


# --- users --------------------------------------------------------------------
class NewUser(BaseModel):
    username: str = Field(max_length=64)
    display_name: str = Field(default="", max_length=80)
    role: str = "employee"
    password: str = Field(max_length=256)


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    role: str | None = None
    active: bool | None = None


class ResetBody(BaseModel):
    password: str = Field(max_length=256)


@router.get("/users")
def users(admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    rows = state.db.all("SELECT id, username, display_name, role, active, must_change_password, created_at, last_login_at FROM users ORDER BY username")
    return {"users": [{**r, "active": bool(r["active"]), "must_change_password": bool(r["must_change_password"])} for r in rows]}


@router.post("/users")
def add_user(body: NewUser, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    try:
        uid = state.accounts.create_user(body.username, body.display_name, body.password, body.role, must_change=True)
    except ValueError as exc:
        return _bad(str(exc))
    state.events.record("admin", "user.created", "Account created", user_id=admin.id, details={"new_user": f"user-{uid}", "role": body.role})
    return {"id": uid}


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    target = state.db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not target:
        return _bad("Account not found.", 404)
    demoting = (body.role == "employee" or body.active is False) and target["role"] == "admin"
    if demoting and state.accounts.admin_count() <= 1:
        return _bad("This is the last administrator account. Add another administrator first.")
    if body.role and body.role not in ("employee", "admin"):
        return _bad("Unknown role.")
    fields = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "active" in fields:
        fields["active"] = int(fields["active"])
    if fields:
        state.db.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), user_id))
        if body.active is False or body.role:
            state.db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    state.events.record("admin", "user.updated", "Account changed", user_id=admin.id,
                        details={"target": f"user-{user_id}", "fields": sorted(fields)})
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: ResetBody, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    if not state.db.one("SELECT 1 FROM users WHERE id = ?", (user_id,)):
        return _bad("Account not found.", 404)
    try:
        state.accounts.set_password(user_id, body.password, must_change=True)
    except ValueError as exc:
        return _bad(str(exc))
    state.events.record("admin", "user.password_reset", "Temporary password set", user_id=admin.id, details={"target": f"user-{user_id}"})
    return {"ok": True}


# --- settings & diagnostics ---------------------------------------------------
@router.get("/settings")
def get_settings(admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    return {"settings": state.settings.all()}


@router.patch("/settings")
def patch_settings(body: dict[str, Any], admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    try:
        values = state.settings.update(body)
    except SettingsError as exc:
        return JSONResponse({"error": "invalid", "message": "Some settings are invalid.", "details": exc.args[0]}, status_code=400)
    state.events.record("admin", "settings.updated", "Station settings changed", user_id=admin.id, details={"keys": sorted(body)})
    return {"settings": values}


@router.get("/diagnostics/health")
def health(admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    return state.diagnostics.health()


@router.get("/diagnostics/events")
def events(q: str = "", level: str = "", category: str = "", printer_id: str = "", job_id: str = "",
           correlation_id: str = "", since: float | None = None, until: float | None = None,
           before_id: int | None = None, limit: int = 100, admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    return state.diagnostics.search(q=q, level=level, category=category, printer_id=printer_id, job_id=job_id,
                                    correlation_id=correlation_id, since=since, until=until, before_id=before_id, limit=limit)


@router.get("/diagnostics/report")
def report(days: int = 3, correlation_id: str = "", admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    data = state.diagnostics.report(days=max(1, min(days, 30)), correlation_id=correlation_id)
    state.events.record("admin", "report.exported", "Support report exported", user_id=admin.id,
                        details={"days": days, "correlation_id": correlation_id or None})
    name = f"printhub-report-{time.strftime('%Y%m%d-%H%M%S')}.json"
    return Response(json.dumps(data, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/maintenance/cleanup")
def cleanup(admin: User = Depends(admin_user), state: AppState = Depends(hub)):
    return state.run_cleanup()
