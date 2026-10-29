# Diagnostics

## Correlation IDs

Every print request gets a correlation ID (`c-xxxxxxxxxxxx`). It links:

- the upload validation and capability read for that request,
- the selected options and every submission attempt with its CUPS response,
- the CUPS job number(s) (`backend_job_id`) for each file,
- every state change polled from CUPS, with IPP `job-state-reasons`,
- cancellations, retries and timeouts.

People see it at the bottom of a job's timeline ("Reference for support"). Admins can paste it into **Admin → Diagnostics → Correlation ID** to see the whole chain, and match CUPS job numbers against `/var/log/cups/page_log` and `error_log`.

## What is recorded

| Category | Examples |
|---|---|
| `upload` / `validation` | upload received; accepted (type, size, pages); rejected with reason code |
| `preparation` | file prepared, converted copy used (e.g. WebP → PNG) |
| `capability` | capabilities read / failed |
| `submission` | job created (settings, file order), attempt (queue, exact `lp` options), accepted (CUPS job number), failed, duplicate blocked |
| `job_state` | queued, processing, stopped, completed, failed (aborted), lost |
| `printer` | status changes with IPP `printer-state-reasons` and reachability results |
| `cancel` / `retry` / `timeout` | requests and outcomes; "stuck" jobs |
| `auth` / `admin` | sign-ins (no passwords), account and settings changes |
| `service` / `cleanup` | start/stop, unclean restart, CUPS unreachable/recovered, background-task errors, retention runs |

Each event has a timestamp, level, category, event code, message and structured details. The diagnostics screen shows a plain-language explanation beside each event code, with the technical details expandable.

## Health

Admin → Diagnostics shows CUPS reachability, database, disk space, background loops (job tracking, printer status, cleanup), storage use, per-printer status, uptime and version. `sudo printhub-admin check` prints the same from a terminal.

## Visibility limits (important)

- CUPS "completed" means CUPS finished delivering the job. Most printers don't report physical output, jams after acceptance, or pages actually printed. The hub says "reported done" and asks people to collect their pages.
- Printer status, supplies and faults appear only when the printer reports them through IPP. Missing data is shown as **unknown**, never as healthy.
- Reachability is probed only for `ipp://`, `ipps://`, `socket://`, `lpd://` and `http(s)://` device URIs. Network-discovered (`dnssd://`) and USB queues rely on CUPS's own reports.
- A CUPS queue showing "idle" doesn't prove a network printer is on. The hub's TCP probe catches many of these cases; CUPS finds out for certain only when it next sends a job.

## Log locations

| Log | Location | Retention |
|---|---|---|
| Hub events (JSON lines) | `/var/log/printhub/printhub.jsonl` (+ `.1`…`.5`) | 5 × 5 MB rotation |
| Hub events (searchable) | SQLite `events` table → Admin → Diagnostics | 30 days (setting) |
| Service stdout/stderr | `journalctl -u printhub` | journald limits |
| CUPS scheduler | `/var/log/cups/error_log` (raise detail with `sudo cupsctl --debug-logging`, revert with `--no-debug-logging`) | logrotate (Mint default) |
| CUPS pages | `/var/log/cups/page_log` | logrotate |
| CUPS access | `/var/log/cups/access_log` | logrotate |
| System | `journalctl -b` | journald |

## Support report

Admin → Diagnostics → **Support report** downloads a JSON file with health, settings, recent jobs (no file names) and the last 3 days of events. People appear as `user-<id>`; file names, document contents, passwords and tokens are never included. Device URIs (printer IP addresses) are included because they're needed for troubleshooting.
