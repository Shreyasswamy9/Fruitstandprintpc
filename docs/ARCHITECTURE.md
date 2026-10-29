# Architecture

```
 Browser (station window or office device)
   │  same origin: http://<station>:8080   (UI + /api)
   ▼
 FastAPI service  (user: printhub, systemd)
   ├─ api/            HTTP routes, auth, CSRF guard, security headers
   ├─ security.py     accounts, scrypt hashes, sessions, login throttling
   ├─ documents.py    upload streaming, size caps, retention  ──► inspect_worker.py (separate process, CPU/memory/time limits)
   ├─ jobs.py         idempotent creation, per-file submission, polling, cancel/retry/reprint, restart recovery
   ├─ registry.py     configured printers, cached status + capabilities
   ├─ printers/       PrinterAdapter interface
   │    ├─ cups.py    production: IPP queries over the CUPS socket, `lp`/`cancel` for submit/cancel
   │    ├─ demo.py    simulated printers (demo mode only)
   │    ├─ ipp.py     minimal IPP client
   │    ├─ capabilities.py  IPP attributes → hub capabilities; strict settings validation
   │    └─ explain.py plain-language reason texts
   ├─ events.py       structured events → SQLite + rotating JSON log
   ├─ diagnostics.py  health, search, redacted support reports
   └─ db.py           SQLite (WAL) + numbered migrations
   ▼
 CUPS (cupsd) ──► printers (IPP / socket / USB)
```

**Boundaries.** The browser never talks to printers. Only `printers/` knows about CUPS. The job service talks to printers only through the `PrinterAdapter` interface, so new printer types or a different print system can be added without changing the UI or the job logic.

**Modes.** `PRINTHUB_MODE=production` uses CUPS only. `demo` uses simulated printers only. The app refuses to start if the adapter and mode disagree, so production can never fall back to simulated success. Demo jobs are flagged `simulated` and every screen labels them as such.

## Job lifecycle

A hub job contains one or more files ("items"). Each item becomes one CUPS job, submitted in order.

| Item state | Meaning |
|---|---|
| `ready` | Validated, waiting to be sent |
| `submitting` | Being handed to CUPS right now |
| `queued` / `held` | Accepted by CUPS, waiting |
| `processing` | CUPS is sending it to the printer |
| `stopped` | CUPS paused it (usually a printer problem) |
| `completed` | **CUPS reports** it finished. Not proof that paper came out. |
| `cancelled` | Cancelled by user, admin, or at the printer |
| `failed` | Not accepted, or aborted by CUPS |
| `unknown` | Outcome uncertain: CUPS forgot the job, a restart happened mid-submission, or submission timed out |

Job status is derived from its items: `submitting`, `in_progress`, `completed`, `partial`, `failed`, `cancelled`, `unknown`. The `attention` flag is set as soon as any file fails, even while others are still printing.

**Duplicate prevention.** The browser creates a random submission key when the review dialog opens. `(owner, key)` is unique in the database, so double-clicks, refreshes and network retries return the existing job.

**Retry.** Only items that never reached CUPS are resent automatically. Items that may have reached the printer (`unknown`, or aborted by CUPS) are resent only after the person explicitly confirms the duplicate risk.

**Restart recovery.** On startup, `submitting` items become `unknown` (they may or may not have reached CUPS). `ready` items become `failed`, marked as safe to retry. Nothing is resent automatically.

## Capabilities

Capabilities come from the printer's IPP attributes as reported by CUPS (`Get-Printer-Attributes`), including copies, color modes, sides, media, orientation, page ranges, scaling, trays, media types, quality, collation, finishings and accepted formats. The settings panel offers only these options. The server re-reads capabilities when the job is submitted and rejects unsupported values with a 422; it never substitutes a different value. Presets are checked against each printer, and anything a printer can't do is listed for the person.

## Persistence (SQLite)

`users`, `sessions` (token hashes only), `files` (metadata; bytes live on disk under random names), `printers`, `presets`, `jobs`, `job_items`, `events`, `settings`. Schema changes are numbered migrations in `db.py`, applied automatically at startup (`PRAGMA user_version`).
