from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..app import AppState, hub
from ..events import new_correlation_id
from ..security import User, verify_password
from .deps import COOKIE, current_user

router = APIRouter(prefix="/api")


class LoginBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/bootstrap")
def bootstrap(request: Request, state: AppState = Depends(hub)):
    """Public, non-sensitive information the sign-in screen needs."""
    return {
        "version": __version__,
        "mode": state.config.mode,
        "station": request.state.station,
        "settings": state.settings.public(),
        "needs_admin_setup": state.accounts.admin_count() == 0,
        "limits": {
            "max_file_mb": state.config.max_file_mb,
            "max_files_per_job": state.config.max_files_per_job,
            "max_pdf_pages": state.config.max_pdf_pages,
            "types": ["PDF", "JPEG", "PNG", "WebP"],
        },
    }


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, state: AppState = Depends(hub)):
    client = request.client.host if request.client else "?"
    keys = (f"u:{body.username.strip().lower()}", f"ip:{client}")
    wait = state.throttle.locked_for(*keys)
    if wait > 0:
        state.events.record("auth", "auth.locked", "Sign-in blocked after repeated failures", level="warning",
                            details={"client": client, "retry_after_s": round(wait)})
        return JSONResponse({"error": "locked", "message": f"Too many attempts. Try again in {int(wait // 60) + 1} minute(s)."},
                            status_code=429)
    row = state.accounts.authenticate(body.username, body.password)
    if not row:
        state.throttle.fail(*keys)
        state.events.record("auth", "auth.login_failed", "Sign-in failed", level="warning", details={"client": client})
        return JSONResponse({"error": "bad_credentials", "message": "That username and password don't match."}, status_code=401)
    state.throttle.clear(*keys)
    station = bool(request.state.station)
    token = state.accounts.create_session(row["id"], station=station)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=state.config.secure_cookies,
                        max_age=state.config.session_hours * 3600 if not station else None, path="/")
    state.events.record("auth", "auth.login", "Signed in" + (" at the station" if station else ""), user_id=row["id"],
                        correlation_id=new_correlation_id(), details={"client": client, "station": station})
    return {"user": state.accounts.resolve(token).public()}


@router.post("/auth/logout")
def logout(request: Request, response: Response, state: AppState = Depends(hub)):
    state.accounts.end_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, state: AppState = Depends(hub)):
    """Who is signed in. Returns {"user": null} rather than 401 so the sign-in screen loads quietly."""
    user = state.accounts.resolve(request.cookies.get(COOKIE))
    return {"user": user.public() if user else None}


@router.post("/auth/password")
def change_password(body: PasswordBody, request: Request, response: Response, user: User = Depends(current_user),
                    state: AppState = Depends(hub)):
    row = state.db.one("SELECT password_hash FROM users WHERE id = ?", (user.id,))
    if not verify_password(body.current_password, row["password_hash"]):
        return JSONResponse({"error": "bad_credentials", "message": "Your current password is not correct."}, status_code=400)
    if body.new_password == body.current_password:
        return JSONResponse({"error": "same_password", "message": "Choose a password you haven't just used."}, status_code=400)
    try:
        state.accounts.set_password(user.id, body.new_password, must_change=False)
    except ValueError as exc:
        return JSONResponse({"error": "weak_password", "message": str(exc)}, status_code=400)
    state.events.record("auth", "auth.password_changed", "Password changed", user_id=user.id)
    token = state.accounts.create_session(user.id, station=user.station)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=state.config.secure_cookies, path="/",
                        max_age=state.config.session_hours * 3600 if not user.station else None)
    return {"user": state.accounts.resolve(token).public()}
