"""FastAPI application factory and background workers."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__
from .config import Config
from .db import Database, dumps, now
from .diagnostics import Diagnostics
from .documents import FileStore, UploadError
from .events import EventLog, setup_logging
from .jobs import JobError, JobService
from .printers.base import AdapterError, PrinterAdapter
from .registry import PrinterNotFound, PrinterRegistry
from .security import Accounts, LoginThrottle
from .settings import Settings

DEFAULT_PRESETS = [
    ("Everyday documents", "Black & white, double-sided — the sensible default.",
     {"color_mode": "monochrome", "sides": "two-sided-long-edge", "quality": "normal"}),
    ("Color presentation", "Full color, single-sided, high quality, fit to page.",
     {"color_mode": "color", "sides": "one-sided", "quality": "high", "scaling": "fit"}),
    ("Draft", "Fast, toner-saving black & white, double-sided.",
     {"color_mode": "monochrome", "sides": "two-sided-long-edge", "quality": "draft"}),
]


class AppState:
    """Holds every service; one instance per running application."""

    def __init__(self, config: Config, adapter: PrinterAdapter | None = None):
        self.config = config
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self.logger = setup_logging(config.log_dir, config.log_max_bytes, config.log_backups)
        self.db = Database(config.db_path)
        self.events = EventLog(self.db, self.logger)
        self.settings = Settings(self.db)
        self.accounts = Accounts(self.db, config.session_hours)
        self.throttle = LoginThrottle(config.login_max_failures, config.login_lockout_minutes * 60)
        if adapter is None:
            if config.demo:
                from .printers.demo import DemoAdapter

                adapter = DemoAdapter()
            else:
                from .printers.cups import CupsAdapter

                adapter = CupsAdapter(socket_path=config.cups_socket, host=config.cups_host, port=config.cups_port,
                                      timeout=config.cups_timeout_s, lp_timeout=config.lp_timeout_s, user=config.service_user)
        if config.demo != adapter.simulated:
            raise RuntimeError("Adapter does not match the configured mode; refusing to mix simulated and real printing.")
        self.files = FileStore(config, self.db, self.events)
        self.registry = PrinterRegistry(self.db, self.events, adapter)
        self.jobs = JobService(config, self.db, self.events, self.files, self.registry, self.settings)
        self.diagnostics = Diagnostics(self)
        self.started_at = time.time()
        self.loop_runs: dict[str, float] = {}
        self._marker = config.data_dir / "running.marker"

    def seed(self) -> None:
        if not self.db.one("SELECT 1 FROM presets LIMIT 1"):
            t = now()
            for order, (name, desc, settings) in enumerate(DEFAULT_PRESETS):
                self.db.execute(
                    "INSERT INTO presets (name, description, settings, builtin, sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (name, desc, dumps(settings), 1, order, t, t),
                )
        self.registry.sync_demo()

    def startup(self) -> None:
        if self._marker.exists():
            self.events.record("service", "service.unclean_restart", "Previous run did not shut down cleanly", level="warning")
        self._marker.write_text(str(time.time()))
        self.seed()
        self.events.record("service", "service.started", f"Print Hub {__version__} started in {self.config.mode} mode",
                           details={"version": __version__, "mode": self.config.mode, "adapter": self.registry.adapter.name})
        self.jobs.recover_after_restart()

    def shutdown(self) -> None:
        self.jobs.shutdown()
        self.events.record("service", "service.stopped", "Print Hub stopped")
        self._marker.unlink(missing_ok=True)

    def run_cleanup(self) -> dict[str, Any]:
        files = self.files.cleanup_expired()
        jobs = self.jobs.purge_history(self.settings.get("history_retention_days"))
        cutoff = now() - self.settings.get("event_retention_days") * 86400
        events = self.db.execute("DELETE FROM events WHERE ts < ?", (cutoff,)).rowcount
        sessions = self.accounts.purge_expired()
        result = {**files, "jobs_purged": jobs, "events_purged": events, "sessions_purged": sessions}
        self.events.record("cleanup", "cleanup.completed", "Retention cleanup finished", details=result)
        return result


async def _loop(state: AppState, name: str, interval: float, fn) -> None:
    log = logging.getLogger("printhub")
    while True:
        try:
            await asyncio.to_thread(fn)
            state.loop_runs[name] = time.time()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("background loop %s failed", name)
            state.events.record("service", "loop.error", f"Background task “{name}” failed", level="error",
                                details={"error": repr(exc)[:300]})
        await asyncio.sleep(interval)


def _is_loopback(host: str | None) -> bool:
    try:
        return bool(host) and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_app(config: Config | None = None, adapter: PrinterAdapter | None = None) -> FastAPI:
    config = config or Config.from_env()
    state = AppState(config, adapter)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state.startup()
        tasks = []
        if config.background_tasks:
            tasks = [
                asyncio.create_task(_loop(state, "status", config.status_interval_s,
                                          lambda: (state.registry.refresh_status(), state.registry.warm_capabilities()))),
                asyncio.create_task(_loop(state, "poll", config.poll_interval_s, state.jobs.poll_once)),
                asyncio.create_task(_loop(state, "cleanup", config.cleanup_interval_s, state.run_cleanup)),
            ]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            state.shutdown()

    app = FastAPI(title="Fruitstand Print Hub", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.hub = state

    @app.middleware("http")
    async def guard(request: Request, call_next):
        request.state.station = _is_loopback(request.client.host if request.client else None)
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            # CSRF defence: browsers cannot add this header cross-site without CORS, which we never grant.
            if request.headers.get("x-printhub") != "1":
                return JSONResponse({"error": "csrf", "message": "Request blocked: missing client header."}, status_code=403)
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"error": "csrf", "message": "Request blocked: cross-site origin."}, status_code=403)
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
            "worker-src 'self' blob:; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'",
        )
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(JobError)
    async def job_error(_: Request, exc: JobError):
        return JSONResponse({"error": exc.code, "message": exc.message, "details": exc.details}, status_code=exc.status)

    @app.exception_handler(UploadError)
    async def upload_error(_: Request, exc: UploadError):
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(AdapterError)
    async def adapter_error(_: Request, exc: AdapterError):
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=503)

    @app.exception_handler(PrinterNotFound)
    async def printer_missing(_: Request, exc: PrinterNotFound):
        return JSONResponse({"error": "printer_missing", "message": "Printer not found."}, status_code=404)

    from .api import admin, auth, files, jobs, printers

    for module in (auth, files, printers, jobs, admin):
        app.include_router(module.router)

    static = config.static_dir
    if static and static.exists():
        index = static / "index.html"

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"error": "not_found", "message": "Unknown API endpoint."}, status_code=404)
            candidate = (static / path).resolve()
            if path and candidate.is_file() and static.resolve() in candidate.parents:
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
                return FileResponse(candidate, headers=headers)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def hub(request: Request) -> AppState:
    return request.app.state.hub
