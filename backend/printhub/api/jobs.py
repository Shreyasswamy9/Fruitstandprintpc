from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..app import AppState, hub
from ..security import User
from .deps import current_user

router = APIRouter(prefix="/api/jobs")


class JobItem(BaseModel):
    file_id: str = Field(max_length=64)
    page_ranges: str | None = Field(default=None, max_length=200)


class JobBody(BaseModel):
    idempotency_key: str = Field(max_length=80)
    printer_id: str = Field(max_length=80)
    items: list[JobItem]
    settings: dict[str, Any] = {}
    preset_name: str | None = Field(default=None, max_length=80)


class RetryBody(BaseModel):
    confirm_possible_duplicates: bool = False


class ReprintBody(BaseModel):
    idempotency_key: str = Field(max_length=80)


@router.post("")
def create(body: JobBody, user: User = Depends(current_user), state: AppState = Depends(hub)):
    job, duplicate = state.jobs.create(user, body.model_dump())
    return JSONResponse({"job": job, "duplicate": duplicate}, status_code=200 if duplicate else 202)


@router.get("")
def list_jobs(scope: str = "mine", status: str | None = None, limit: int = 50,
              user: User = Depends(current_user), state: AppState = Depends(hub)):
    return {"jobs": state.jobs.list(user, scope=scope, limit=limit, status=status)}


@router.get("/{job_id}")
def get_job(job_id: str, user: User = Depends(current_user), state: AppState = Depends(hub)):
    return {"job": state.jobs.view(job_id, user)}


@router.get("/{job_id}/timeline")
def timeline(job_id: str, user: User = Depends(current_user), state: AppState = Depends(hub)):
    return {"events": state.jobs.timeline(job_id, user)}


@router.post("/{job_id}/cancel")
def cancel(job_id: str, user: User = Depends(current_user), state: AppState = Depends(hub)):
    return {"job": state.jobs.cancel(job_id, user)}


@router.post("/{job_id}/retry")
def retry(job_id: str, body: RetryBody, user: User = Depends(current_user), state: AppState = Depends(hub)):
    return {"job": state.jobs.retry(job_id, user, body.confirm_possible_duplicates)}


@router.post("/{job_id}/reprint")
def reprint(job_id: str, body: ReprintBody, user: User = Depends(current_user), state: AppState = Depends(hub)):
    job, duplicate = state.jobs.reprint(job_id, user, body.idempotency_key)
    return JSONResponse({"job": job, "duplicate": duplicate}, status_code=200 if duplicate else 202)
