# Operations

## Day-to-day

| Task | Command |
|---|---|
| Service status | `systemctl status printhub` |
| Restart service | `sudo systemctl restart printhub` |
| Health summary | `sudo printhub-admin check` |
| Service log | `journalctl -u printhub -e` |
| App event log | `/var/log/printhub/printhub.jsonl` (also Admin → Diagnostics) |
| CUPS logs | `/var/log/cups/error_log`, `/var/log/cups/page_log`, `/var/log/cups/access_log` |
| CUPS queue | `lpstat -t` · `lpstat -W all -o` |
| Reset a password | `sudo printhub-admin reset-password <username>` |
| Run cleanup now | Admin → Diagnostics → *Run cleanup now*, or `sudo printhub-admin cleanup` |

## CUPS

The hub uses the normal local CUPS scheduler.

- **Add a printer:** prefer driverless IPP Everywhere. `lpinfo -v` lists discovered devices. Then
  `sudo lpadmin -p <QueueName> -E -v ipp://<printer-ip>/ipp/print -m everywhere -L "<location>"`.
  Use a fixed IP or DHCP reservation for each printer; `dnssd://` URIs depend on mDNS working on the network.
  Fall back to a vendor PPD/driver only when the printer isn't IPP Everywhere capable, and record it in PRINTERS.md.
- **Keep CUPS administration restricted.** Leave `cupsd.conf` at its Mint default: the web interface is local-only and admin actions require `lpadmin` membership. The `printhub` user is deliberately **not** in `lpadmin`. Don't share printers from CUPS to the network; coworkers print through the hub.
- **Error policy:** `sudo lpadmin -p <Queue> -o printer-error-policy=retry-job` makes CUPS retry jobs while a printer is briefly unreachable instead of stopping the queue. The hub reports stopped queues as "Paused".
- **Job history:** the hub tracks jobs through CUPS's job records. Keep CUPS's default `PreserveJobHistory Yes`. If CUPS purges a job before the hub reads its final state, the hub shows it as "Outcome unknown", never as success.

## Network

1. Find the station's address: `ip -4 -brief addr`. Give it a DHCP reservation so the address doesn't change.
2. **Verify reachability before configuring anything.** From another office device, open `http://<station-ip>:8080`. If it doesn't load:
   - test from the station itself (`curl http://<station-ip>:8080/api/health`): if that fails, the issue is local (firewall or bind address);
   - if the station works locally but other devices can't reach it, the Wi-Fi may be isolating clients ("AP/client isolation", common on guest networks). **That is a network policy decision for whoever runs the office network.** Options are a wired connection for the station, a non-isolated SSID/VLAN for staff, or a rule allowing TCP 8080 to the station. Don't work around isolation with tunnels or external services.
3. Firewall (recommended once reachability is confirmed):
   ```bash
   sudo ufw allow from <office-subnet, e.g. 192.168.1.0/24> to any port 8080 proto tcp
   sudo ufw allow from <admin-subnet> to any port 22 proto tcp   # if SSH is approved
   sudo ufw enable
   ```
4. Never port-forward 8080 from the router. The hub is for the office LAN only.
5. Optional: a friendly name such as `print.local`. Avahi advertises `<hostname>.local`, so `http://<hostname>.local:8080` works on most Macs/iPhones and on Windows with mDNS. A DNS entry on the office router is more reliable.

**HTTPS.** By default the hub serves plain HTTP on the LAN, so passwords cross the office network unencrypted. To add TLS, put a reverse proxy (e.g. Caddy with an internal CA, or nginx with a certificate from your own CA installed on office devices) in front of the hub on port 443, bind the hub to `127.0.0.1`, and set `PRINTHUB_SECURE_COOKIES=true`. Self-signed certificates without an installed CA produce browser warnings that train people to click through, so avoid them.

## Station display

- Autostart: `deploy/setup-station.sh <user>` opens the hub after the station account logs in, in a maximized app window (`--kiosk` for full screen).
- **Maintenance exit:** `Esc` leaves browser full screen; `Ctrl+Shift+Q` or `Alt+F4` closes the dashboard window. The launcher does **not** relaunch it, so the desktop is reachable. Reopen from the menu (*Print Hub*). To get an admin shell: `Ctrl+Alt+T`, or switch user, or `Ctrl+Alt+F3` for a text console.
- Remove autostart: `sudo deploy/setup-station.sh <user> --remove`.
- People sign in at the station with their own account and are signed out after the configured idle time (Admin → Settings), with a 30-second on-screen warning.
- The station account should not have sudo. Screen lock is turned off by `station-power.sh` because the hub has its own sign-in; the desktop session itself is therefore open to anyone at the laptop, which is why that account must be unprivileged.

## Power

`deploy/station-power.sh <user>` (review with `--show` first): no suspend on AC when idle or when the lid closes, display sleeps after 30 minutes, screen lock off for the station account. The service runs independently of the desktop session. Use BIOS "power on after AC loss" if the laptop supports it.

## Behaviour after events

| Event | What happens |
|---|---|
| Reboot | systemd starts `printhub` after CUPS and the network. In-flight files are settled safely (see ARCHITECTURE › Restart recovery). The station account's autostart waits up to 60 s for the service. |
| Service crash | systemd restarts it within 3 s. Diagnostics shows "previous run did not shut down cleanly". |
| Network loss | Browsers on other devices lose the page; the station keeps working locally. Uploads in progress fail with a clear message and can be re-added. Network printers become unreachable: CUPS queues jobs (or stops the queue, depending on error policy) and the hub shows the CUPS state. |
| Printer off / unplugged | CUPS reports the printer offline or stops the queue; cards show "Offline" or "Paused" and block new jobs. Jobs already queued wait in CUPS. |
| Printer reconnected | CUPS resumes (or an admin runs `cupsenable <Queue>` if the queue stopped). The hub picks up the state within ~20 s; *Admin → Printers → refresh* checks immediately. |
| CUPS stopped | Printer status becomes "Status unknown", job tracking pauses, and a "print system is not responding" event is logged. New jobs fail with an explanation rather than appearing to succeed. |

## Remote administration (approved methods)

- **SSH** from the office network only, key-based, admin account only: `sudo apt install openssh-server`, set `PasswordAuthentication no`, firewall as above. Use it for `systemctl`, `journalctl`, `printhub-admin`, updates.
- The hub's **Admin** pages work from any office browser for administrators. Use them for printers, people, presets, diagnostics and settings.
- CUPS web admin (`http://localhost:631`) stays local to the station; over SSH use `ssh -L 6310:localhost:631 admin@station` and open `http://localhost:6310`.
- Don't install remote-desktop tools exposed to the internet.

## Backup and restore

- **Automatic:** `printhub-backup.timer` runs daily at 03:15 and keeps 14 copies in `/var/lib/printhub/backups/`. Copy these off the laptop periodically (e.g. to a NAS or USB drive).
- **Manual:** `sudo printhub-admin backup /var/lib/printhub/backups`
- **What's in a backup:** accounts (password hashes), printers, presets, settings, job history and events. Uploaded files are not included; they're short-lived by design. `/etc/printhub/printhub.env` and CUPS queues (`/etc/cups/printers.conf`, `/etc/cups/ppd/`) should be backed up separately: `sudo tar czf printhub-config.tgz /etc/printhub /etc/cups`.
- **Restore:**
  ```bash
  sudo systemctl stop printhub
  sudo printhub-admin restore /var/lib/printhub/backups/printhub-YYYYMMDD-HHMMSS.sqlite3 --yes
  sudo systemctl start printhub
  ```
  The current database is kept beside it as `printhub.before-restore-<time>`.

## Update and rollback

```bash
sudo /opt/printhub/current/deploy/update.sh printhub-<new>.tar.gz
```

Backs up the database, installs the new release side by side, switches `/opt/printhub/current`, restarts and health-checks. If the health check fails, it switches back and restores the pre-update database. The last three releases are kept.

Manual rollback: `sudo /opt/printhub/current/deploy/update.sh --rollback`. If the newer release ran a database migration, also restore the pre-update backup (newest file in `/var/lib/printhub/backups/` from before the update).

## Recovery checklist

1. `systemctl status printhub` and `journalctl -u printhub -n 100`.
2. `sudo printhub-admin check` (CUPS, database, disk, printers).
3. `lpstat -t` for CUPS's view; `sudo systemctl restart cups` if the scheduler is wedged.
4. Disk full? Check `df -h /var`, then run cleanup.
5. Database damaged? Stop the service, restore the latest backup (above).
6. Locked out of every admin account? `sudo printhub-admin create-admin <newname>` or `reset-password <name>`.
7. Still stuck: Admin → Diagnostics → *Support report* (or the JSON log) and hand it to support. It is redacted.

## Printer firmware

Firmware updates are manufacturer-specific (printer web panel or vendor tool). The hub doesn't update firmware. After a firmware update, refresh the printer in Admin → Printers and re-check its capabilities.
