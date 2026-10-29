# Access and privacy

## Decision needed before rollout: how people sign in

The office network alone isn't treated as identification, because anyone on the Wi-Fi could otherwise see or cancel others' jobs. What's built today:

**Local accounts (implemented).** An administrator creates each person in Admin → People. They get a temporary password and choose their own at first sign-in. Passwords are hashed with scrypt; sessions are random tokens stored only as hashes; failed sign-ins are throttled (5 per 5 minutes per username and per address).

| Option | Pros | Cons |
|---|---|---|
| **Local accounts** (current) | Works fully offline; no external dependency; simple | Another password for staff; admins handle resets |
| Google Workspace / SSO | No new password | Needs internet to sign in, which conflicts with "printing works offline"; needs an OAuth app and HTTPS |
| Shared PIN per person | Fast at the station | Weak if PINs are short; still needs per-person records |
| No sign-in | Easiest | No privacy, no attribution. **Not recommended** |

Recommendation: keep local accounts. If faster station sign-in is wanted later, add a per-person PIN usable **only at the station** (loopback sessions) while office devices keep full passwords. That's a small, contained change.

## What each role can do

| | Employee | Administrator |
|---|---|---|
| Upload, preview, print | ✓ own files | ✓ own files |
| See / cancel / retry jobs | own only | all jobs (station queue) |
| Open document contents | own only | **no**; admins can't open employees' files |
| See file names in the queue | own only | hidden ("PDF file 1") |
| Reprint | own, while files are retained | own only |
| Printers, presets, people, settings, diagnostics | – | ✓ |

All of this is enforced on the server. Requests for someone else's job or file return "not found", so IDs can't be probed.

## Protections

- Same-origin only; no CORS. Every state-changing request needs the `X-PrintHub` header, and a cross-site `Origin` is rejected (CSRF). Cookies are `HttpOnly`, `SameSite=Strict`.
- Content-Security-Policy restricts scripts to the hub itself; documents are served with a sandbox CSP and `nosniff`.
- Uploaded file names are display-only and never used as paths. Bytes are stored as `<random>.bin` in a 0700 directory owned by the service user.
- File content is checked from its bytes (not its name) in a separate process with CPU, memory and time limits.
- Uploads never print automatically; a job is created only on explicit confirmation.
- The service runs as the unprivileged `printhub` user under a hardened systemd unit (read-only system, private /tmp, no capabilities). It isn't in `lpadmin`, so it can't administer CUPS.
- Logs never contain passwords, session tokens or document contents; sensitive keys are redacted defensively. Events refer to people as `user-<id>`.
- Retention: uploaded files are deleted after 24 h by default (later if a job still needs them), job history after 90 days, events after 30 days.

## Not exposed to the internet

Bind to the LAN, restrict with `ufw` to the office subnet, and never port-forward. See OPERATIONS.md › Network. Plain HTTP means passwords cross the LAN unencrypted; add TLS as described there if the network isn't fully trusted.
