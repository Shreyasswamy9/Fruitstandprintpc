# Configuration

## Service settings — `/etc/printhub/printhub.env`

Restart the service after changes: `sudo systemctl restart printhub`.

| Variable | Default | Purpose |
|---|---|---|
| `PRINTHUB_MODE` | `production` | `production` = CUPS only; `demo` = simulated printers only |
| `PRINTHUB_DATA_DIR` | `/var/lib/printhub` | Database, uploads, backups |
| `PRINTHUB_LOG_DIR` | `/var/log/printhub` | Rotating JSON event log |
| `PRINTHUB_STATIC_DIR` | – | Built frontend (`/opt/printhub/current/frontend/dist`) |
| `PRINTHUB_HOST` / `PRINTHUB_PORT` | `0.0.0.0` / `8080` | Listen address. Use `127.0.0.1` behind a TLS proxy |
| `PRINTHUB_MAX_FILE_MB` | `50` | Per-file upload limit |
| `PRINTHUB_MAX_FILES_PER_JOB` | `20` | Files per job (each person can hold 3× this many uploads) |
| `PRINTHUB_MAX_PDF_PAGES` | `500` | Pages per PDF |
| `PRINTHUB_MAX_IMAGE_MEGAPIXELS` | `80` | Image size limit |
| `PRINTHUB_INSPECT_TIMEOUT_S` | `30` | Wall/CPU time for checking one file |
| `PRINTHUB_INSPECT_MEMORY_MB` | `768` | Memory cap for the file checker (Linux) |
| `PRINTHUB_SESSION_HOURS` | `12` | Sign-in lifetime on office devices (station sessions end when the window closes or after idle time) |
| `PRINTHUB_SECURE_COOKIES` | `false` | Set `true` when served over HTTPS |
| `PRINTHUB_CUPS_SOCKET` | auto | CUPS Unix socket (auto-detects `/run/cups/cups.sock`) |
| `PRINTHUB_CUPS_HOST` / `PRINTHUB_CUPS_PORT` | `localhost` / `631` | Used only if no socket is found |
| `PRINTHUB_SERVICE_USER` | `printhub` | `requesting-user-name` sent to CUPS |
| `PRINTHUB_POLL_INTERVAL_S` | `3` | Job-state polling interval |
| `PRINTHUB_STUCK_JOB_MINUTES` | `20` | Flag jobs that haven't started after this long |
| `PRINTHUB_LOG_MAX_BYTES` / `PRINTHUB_LOG_BACKUPS` | `5 MB` / `5` | JSON log rotation |

## Station settings — Admin → Settings

Stored in the database and take effect immediately.

| Setting | Default | Notes |
|---|---|---|
| Station name / subtitle | Fruitstand Print Hub / Long Island City | Header and sign-in page |
| Station idle sign-out | 3 min | Only for sessions on the station itself |
| Job name on printer panels | Name + reference | "File name" exposes document names to anyone at the printer |
| File retention | 24 h | Files in active jobs are kept until the job finishes. Reprint needs the file |
| Job history retention | 90 days | Active jobs are never purged |
| Event retention | 30 days | Diagnostics events in the database |
| Theme / motion / density | system / full / comfortable | Each device can override the theme; system reduced-motion is always honoured |

## Printers — Admin → Printers

Friendly name, location, illustration, enabled state, notes, and per-printer defaults (color, sides, paper, quality), chosen from what that printer reports.

## Presets — Admin → Presets

Three are seeded: *Everyday documents*, *Color presentation*, *Draft*. Values are standard IPP keywords and are validated against each printer when applied.
