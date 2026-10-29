# Installing on the Linux Mint station

> **Status:** these steps have not been run on the station yet. The development machine was macOS. Run the `--check` step first and compare its output with the expectations below before making changes.

## 0. Before you start

- Station: Linux Mint 22.x (Ubuntu 24.04 base, Python 3.12) is the target. Mint 21.x (Python 3.10) should also work.
- Create two accounts on the laptop if they don't exist:
  - an **administrator** account (sudo), used for maintenance only;
  - a **station** account (no sudo) that logs in automatically and shows the dashboard.
- Make sure you can reach the laptop for maintenance before you enable kiosk mode (see *Recovery access* in OPERATIONS.md).

## 1. Build a release (development machine)

```bash
deploy/make-release.sh            # needs internet for npm; produces dist/printhub-<version>.tar.gz
deploy/make-release.sh --wheels   # optional: bundle Python wheels so the station installs offline
```

Copy the tarball to the station (USB stick or `scp`).

## 2. Inspect the station (nothing is changed)

```bash
tar xzf printhub-0.1.0.tar.gz && cd printhub-0.1.0
sudo ./deploy/install.sh --check
```

This reports the OS, Python, missing packages, CUPS state and queues, whether port 8080 is free, the firewall state and network addresses, followed by the list of planned changes. **Stop and review** if CUPS is not running, port 8080 is in use, or Python is older than 3.10.

## 3. Install

```bash
sudo ./deploy/install.sh --yes --packages   # --packages apt-installs: python3 python3-venv cups cups-client
                                           #   cups-filters cups-ipp-utils avahi-daemon curl sqlite3
```

What it does:

- creates the system user `printhub` (no shell, **not** in `lpadmin`);
- creates `/var/lib/printhub` (data, 0700) and `/var/log/printhub` (logs);
- installs the release to `/opt/printhub/releases/<version>` with its own virtualenv, and points `/opt/printhub/current` at it;
- writes `/etc/printhub/printhub.env` from the example **only if it doesn't exist**;
- installs `printhub.service`, the daily `printhub-backup.timer` and `/usr/local/bin/printhub-admin`;
- starts the service, health-checks it, and rolls back the symlink if it doesn't come up.

It does not change `cupsd.conf`, the firewall, or power settings.

## 4. First administrator

```bash
sudo printhub-admin create-admin <username>
```

Sign in at `http://localhost:8080`, then add people in **Admin → People**. Each new person gets a temporary password that they must change at first sign-in.

## 5. Printers

Follow [PRINTERS.md](PRINTERS.md) for each device: add it to CUPS, connect it in **Admin → Printers**, refresh, print a test page, then run the physical checklist.

## 6. Station display, power, network

```bash
sudo /opt/printhub/current/deploy/setup-station.sh <station-user>          # maximized app window
sudo /opt/printhub/current/deploy/setup-station.sh <station-user> --kiosk  # optional full screen
sudo /opt/printhub/current/deploy/station-power.sh <station-user> --show   # review, then run without --show
```

Then configure the firewall and confirm reachability from another device: OPERATIONS.md › *Network*.

## Demo mode on the station

To show the interface before printers are ready, set `PRINTHUB_MODE=demo` in `/etc/printhub/printhub.env` and restart. A purple banner marks every screen. Switch back to `production` before real use. Demo and production share the database, so demo jobs remain in history (marked simulated) unless you start with a fresh data directory.
