# Fruitstand Print Hub

One consistent way to print in the office. Employees upload a file, choose a printer from a visual grid, adjust only the settings that printer really supports, preview, confirm, and track the job — from the station laptop or from any browser on the office network.

```
Add files → choose printer → adjust settings → preview → confirm → track job
```

## What's here

| Path | What it is |
|---|---|
| `backend/` | Python 3.10+ FastAPI service: API, document checks, CUPS adapter, SQLite, diagnostics |
| `frontend/` | React + TypeScript interface; CSS design system in `src/styles/` |
| `deploy/` | Linux Mint install/update/rollback scripts, systemd units, station launcher |
| `docs/` | Installation, operations, configuration, access, diagnostics, testing, limitations |

## Run it locally (development)

```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest                          # 47 tests

# frontend
cd ../frontend
npm ci && npm run build                   # builds frontend/dist

# demo mode: simulated printers, nothing is ever sent to a real printer
cd ../backend
export PRINTHUB_MODE=demo PRINTHUB_DATA_DIR=/tmp/ph/data PRINTHUB_LOG_DIR=/tmp/ph/logs \
       PRINTHUB_STATIC_DIR=$PWD/../frontend/dist PRINTHUB_PORT=8080
.venv/bin/printhub create-admin admin     # prompts for a password
.venv/bin/printhub serve                  # http://localhost:8080
```

For UI work, `npm run dev` in `frontend/` serves on :5173 and proxies `/api` to :8080.

## Install on the station

See **[docs/INSTALL.md](docs/INSTALL.md)**. In short: `deploy/make-release.sh` on a dev machine, copy the tarball to the station, `sudo ./deploy/install.sh --check` to inspect, then `--yes` to install.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, boundaries, data flow, job states
- [docs/INSTALL.md](docs/INSTALL.md) — first installation on Linux Mint
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — CUPS, network, kiosk, power, backup/restore, update/rollback, recovery
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — every setting
- [docs/ACCESS.md](docs/ACCESS.md) — authentication choice and privacy model
- [docs/DIAGNOSTICS.md](docs/DIAGNOSTICS.md) — correlation IDs, events, log locations, support reports
- [docs/PRINTERS.md](docs/PRINTERS.md) — printer inventory and onboarding procedure
- [docs/TESTING.md](docs/TESTING.md) — automated results and the physical acceptance checklist
- [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) — what is incomplete or unverifiable
- [docs/BRANDING.md](docs/BRANDING.md) — what was taken from fruitstandny.com and what is missing
