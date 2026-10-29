from __future__ import annotations

from fastapi import APIRouter, Depends

from ..app import AppState, hub
from ..db import loads
from ..printers.capabilities import SETTING_LABELS, check_preset
from ..registry import PrinterNotFound
from ..security import User
from .deps import current_user

router = APIRouter(prefix="/api")


@router.get("/printers")
def list_printers(user: User = Depends(current_user), state: AppState = Depends(hub)):
    return {
        "simulated": state.registry.adapter.simulated,
        "printers": [state.registry.public(r) for r in state.registry.rows()],
    }


@router.get("/printers/{printer_id}")
def get_printer(printer_id: str, user: User = Depends(current_user), state: AppState = Depends(hub)):
    row = state.registry.row(printer_id)
    if not row["enabled"] and not user.is_admin:
        raise PrinterNotFound(printer_id)
    return state.registry.public(row, admin=user.is_admin)


@router.get("/printers/{printer_id}/capabilities")
def capabilities(printer_id: str, refresh: bool = False, user: User = Depends(current_user), state: AppState = Depends(hub)):
    row = state.registry.row(printer_id)
    caps = state.registry.capabilities(printer_id, refresh=refresh)
    return {"printer_id": row["id"], "capabilities": caps, "defaults": loads(row["defaults"], {}), "labels": SETTING_LABELS}


@router.get("/presets")
def presets(printer_id: str | None = None, user: User = Depends(current_user), state: AppState = Depends(hub)):
    rows = state.db.all("SELECT * FROM presets ORDER BY sort_order, name")
    caps = state.registry.capabilities(printer_id) if printer_id else None
    out = []
    for r in rows:
        settings = loads(r["settings"], {})
        entry = {"id": r["id"], "name": r["name"], "description": r["description"], "settings": settings, "builtin": bool(r["builtin"])}
        if caps is not None:
            entry["compatibility"] = check_preset(settings, caps)
        out.append(entry)
    return {"presets": out}
