"""Request dependencies: current user and role checks."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from ..app import AppState, hub
from ..security import User

COOKIE = "ph_session"


def current_user(request: Request, state: AppState = Depends(hub)) -> User:
    user = state.accounts.resolve(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail={"error": "signed_out", "message": "Please sign in."})
    if user.must_change_password and request.url.path not in ("/api/auth/me", "/api/auth/password", "/api/auth/logout"):
        raise HTTPException(status_code=403, detail={"error": "password_change_required", "message": "Choose a new password first."})
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail={"error": "forbidden", "message": "Administrator access is required."})
    return user
