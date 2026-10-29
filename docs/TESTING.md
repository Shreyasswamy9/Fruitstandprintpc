# Testing

## Automated tests — `cd backend && .venv/bin/pytest`

Last run 2026-10-28 on macOS (Python 3.14): **49 passed**. Real-printer capability parsing uses attributes captured from a Canon MF750C II.

| Area | Tests |
|---|---|
| File validation | PDF/JPEG/PNG/WebP accepted; WebP converted with an explicit note; unsupported extension (415); disguised executable named `.pdf` rejected by content; mismatched extension handled by content with a note; encrypted PDF rejected; oversize (413) and empty files; `../../etc/passwd.pdf` stored safely; interrupted upload leaves no file; slow or hostile file stopped by the time limit |
| Privacy | other employees and admins can't open or delete someone's file; per-user file lists |
| Capabilities & settings | real Canon attributes normalized; unsupported finishing/media/copies rejected, never substituted; exact IPP option mapping; page-range rules; preset compatibility split |
| Printer status | ready / offline / jam (attention) / stopped from real attributes; supply levels; unknown levels not shown as numbers; reachability probe doesn't claim what it can't check |
| Jobs | order and options preserved; filenames kept off printer panels by default; duplicate submission blocked; unsupported settings send nothing; partial batch failure; retry resends only the failed file; uncertain submission requires explicit confirmation; offline printer fails explicitly; capabilities unavailable blocks printing; processing → completed → lost tracked; cancel queued vs too late; reprint only while files are retained; restart settles in-flight items; demo mode simulated and separate; production refuses a simulated adapter |
| Access | signed-out rejection; CSRF header and cross-origin rejection; employees blocked from admin endpoints; job ownership (view/timeline/cancel/retry/print another's file); admins see all jobs with file names hidden; login throttling; forced password change; last admin protected; passwords and session tokens absent from logs |
| Maintenance | cleanup keeps files used by active jobs; history/event retention; log rotation bounded to N files; redaction; support report free of file names and usernames; diagnostics search by correlation ID and level; test page tracked as a job; settings validation |

## Browser walkthrough (demo mode, headless Chromium)

Covered: sign-in errors, upload with progress, unsupported Office file message, reorder, page range, printer selection, offline printer disabled, presets, advanced options, settings reconciled with a visible notice when switching printers, review dialog with preview of each file, simulated print, live job timeline to "Simulation finished", My jobs, phone layout (390 px, no horizontal overflow), dark mode, admin queue (file names hidden), printers, diagnostics, settings. No JavaScript errors.

## Production adapter against real CUPS (read-only)

On the dev Mac, with the Canon MF750C II queue: discovery, registration, live status, toner levels (52/87/87/84 %), full capability read, and rejection of an unsupported staple request all worked. **No job was printed.** The live-CUPS `lp` submission and `cancel` paths have not run against a real printer yet.

## Not yet tested (needs the station and printers)

- `install.sh`, `update.sh`, rollback, systemd hardening, autostart, power script, on Linux Mint.
- Reachability from other office devices (client isolation).
- Real submission, cancellation, and CUPS state tracking on each office printer.
- Service restart and network loss during real printing.

## Physical acceptance checklist (per printer)

Use the hub test page plus a 4-page PDF with numbered pages and a color image. Record pass/fail and the date in PRINTERS.md.

| # | Check | How | Expected |
|---|---|---|---|
| 1 | Test page | Admin → Printers → Test page | One page; border visible on all sides; swatches and gray steps correct |
| 2 | Page range | Pages `2-3` | Only pages 2 and 3 |
| 3 | Copies + collation | 2 copies, collated on/off | 1-2-3-4,1-2-3-4 vs 1-1,2-2,… |
| 4 | Color vs B&W | Same color page in both modes | Color output vs grayscale (no color toner used) |
| 5 | Duplex long edge | 4 pages, long edge | 2 sheets; backs upright when flipped like a book |
| 6 | Duplex short edge | 4 pages, short edge | Backs upright when flipped top-to-bottom |
| 7 | Orientation | Landscape on a portrait doc | Content rotated as previewed |
| 8 | Scaling | Fit vs actual size on an oversized page | Fit shrinks to page; actual size crops |
| 9 | Paper size | Letter vs Legal (if loaded) | Correct media used or printer prompts |
| 10 | Tray / paper type | Each reported tray | Paper pulled from the selected tray |
| 11 | Image | JPEG and PNG photo, fit | Correct orientation, not stretched |
| 12 | Cancel | Submit 20 pages, cancel while queued | Nothing prints; "Cancelled" shown |
| 13 | Offline | Power the printer off, submit | Card shows Offline/Paused or job waits; no false "done" |
| 14 | Reconnect | Power back on | Waiting job prints once (not twice) |
| 15 | Finishing | Staple/punch if reported | Applied as selected |
