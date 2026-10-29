from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from ..app import AppState, hub
from ..documents import UploadError
from ..events import new_correlation_id
from ..security import User
from .deps import current_user

router = APIRouter(prefix="/api/files")


@router.post("")
async def upload(request: Request, user: User = Depends(current_user), state: AppState = Depends(hub)):
    """Receive one file as the raw request body. The name arrives in X-Filename (URI-encoded)."""
    name = unquote(request.headers.get("x-filename", ""))[:500]
    length = request.headers.get("content-length")
    declared = int(length) if length and length.isdigit() else None
    mine = state.db.one("SELECT COUNT(*) AS n FROM files WHERE owner_id = ? AND status = 'ready'", (user.id,))["n"]
    if mine >= state.config.max_files_per_job * 3:
        raise UploadError("too_many_stored", "You have too many files waiting. Remove some before adding more.", 429)
    return await state.files.receive(
        user.id, name, declared, request.stream(), state.settings.get("file_retention_hours"), new_correlation_id()
    )


@router.get("")
def list_files(user: User = Depends(current_user), state: AppState = Depends(hub)):
    return {"files": state.files.list_for(user.id)}


def _own_file(file_id: str, user: User, state: AppState) -> dict | None:
    row = state.files.get(file_id)
    # Files are private to their owner — administrators cannot open them either.
    if not row or row["owner_id"] != user.id or row["status"] != "ready":
        return None
    return row


@router.get("/{file_id}/content")
def content(file_id: str, user: User = Depends(current_user), state: AppState = Depends(hub)):
    row = _own_file(file_id, user, state)
    if not row:
        return JSONResponse({"error": "not_found", "message": "File not found."}, status_code=404)
    return FileResponse(
        state.files.path_for(row["storage_name"]),
        media_type=row["mime"],
        headers={"Content-Disposition": "inline", "Cache-Control": "private, no-store",
                 "Content-Security-Policy": "sandbox; default-src 'none'"},
    )


@router.delete("/{file_id}")
def delete(file_id: str, user: User = Depends(current_user), state: AppState = Depends(hub)):
    row = _own_file(file_id, user, state)
    if not row:
        return JSONResponse({"error": "not_found", "message": "File not found."}, status_code=404)
    if state.files.in_active_job(file_id):
        return JSONResponse({"error": "in_use", "message": "This file is part of a job that is still printing."}, status_code=409)
    state.files.delete(row, "removed by owner")
    return {"ok": True}
