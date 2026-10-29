#!/usr/bin/env bash
# Install Print Hub on the Linux Mint station from an unpacked release directory.
#
#   sudo ./deploy/install.sh --check      # inspect only: report what exists and what would change
#   sudo ./deploy/install.sh --yes        # perform the install
#   sudo ./deploy/install.sh --yes --packages   # also apt-install required packages
#
# Safe to re-run. It never edits /etc/cups/cupsd.conf, never adds the service
# user to lpadmin, and never overwrites an existing /etc/printhub/printhub.env.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/backend/printhub/__init__.py")"
PREFIX=/opt/printhub
RELEASE="$PREFIX/releases/$VERSION"
PACKAGES=(python3 python3-venv cups cups-client cups-filters cups-ipp-utils avahi-daemon curl sqlite3)

MODE=""; WITH_PACKAGES=0
for arg in "$@"; do
  case "$arg" in
    --check) MODE=check ;;
    --yes) MODE=install ;;
    --packages) WITH_PACKAGES=1 ;;
    *) echo "Unknown option $arg" >&2; exit 2 ;;
  esac
done
[[ -z "$MODE" ]] && { sed -n '2,10p' "$0"; exit 2; }
[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

say() { printf '\033[1m%s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

say "== Environment =="
. /etc/os-release 2>/dev/null && echo "OS: $PRETTY_NAME"
echo "Kernel: $(uname -r)  Arch: $(uname -m)"
echo "Python: $(python3 --version 2>&1 || echo missing)"
for p in "${PACKAGES[@]}"; do
  dpkg -s "$p" >/dev/null 2>&1 && echo "  [installed] $p" || echo "  [missing]   $p"
done
echo "CUPS: $(systemctl is-active cups 2>/dev/null || echo unknown)"
have lpstat && { echo "CUPS queues:"; lpstat -v 2>/dev/null | sed 's/^/  /' || true; }
echo "Port 8080: $(ss -ltn 2>/dev/null | grep -q ':8080 ' && echo IN USE || echo free)"
echo "Service user printhub: $(id printhub >/dev/null 2>&1 && echo exists || echo 'will be created')"
echo "Existing install: $(readlink -f $PREFIX/current 2>/dev/null || echo none)"
echo "Firewall: $(ufw status 2>/dev/null | head -1 || echo 'ufw not installed')"
echo "Network addresses:"; ip -4 -brief addr show scope global 2>/dev/null | sed 's/^/  /' || true

if [[ "$MODE" == check ]]; then
  say "== Planned changes (nothing done) =="
  echo "  - install release $VERSION to $RELEASE and point $PREFIX/current at it"
  echo "  - create system user 'printhub' (no login shell, not in lpadmin)"
  echo "  - create /var/lib/printhub (0700) and /var/log/printhub (0750)"
  echo "  - create /etc/printhub/printhub.env from the example if absent"
  echo "  - install and enable systemd unit printhub.service, plus a daily backup timer"
  echo "  - install /usr/local/bin/printhub-admin (runs the CLI as the service user)"
  [[ $WITH_PACKAGES -eq 1 ]] && echo "  - apt-get install: ${PACKAGES[*]}"
  exit 0
fi

if [[ $WITH_PACKAGES -eq 1 ]]; then
  say "== Installing packages =="
  apt-get update
  apt-get install -y "${PACKAGES[@]}"
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || { echo "Python 3.10+ is required." >&2; exit 1; }

say "== Service user and directories =="
id printhub >/dev/null 2>&1 || useradd --system --home-dir /var/lib/printhub --shell /usr/sbin/nologin printhub
install -d -o printhub -g printhub -m 0700 /var/lib/printhub /var/lib/printhub/backups
install -d -o printhub -g adm -m 0750 /var/log/printhub
install -d -m 0755 /etc/printhub "$PREFIX/releases"

say "== Release $VERSION =="
rm -rf "$RELEASE.tmp"
mkdir -p "$RELEASE.tmp"
cp -R "$SRC/backend" "$SRC/frontend" "$SRC/deploy" "$SRC/docs" "$RELEASE.tmp/"
python3 -m venv "$RELEASE.tmp/venv"
if [[ -d "$SRC/wheels" ]]; then
  "$RELEASE.tmp/venv/bin/pip" install --no-index --find-links "$SRC/wheels" "$RELEASE.tmp/backend"
else
  "$RELEASE.tmp/venv/bin/pip" install "$RELEASE.tmp/backend"
fi
[[ -f "$RELEASE.tmp/frontend/dist/index.html" ]] || { echo "frontend/dist missing — build a release with deploy/make-release.sh" >&2; exit 1; }
rm -rf "$RELEASE" && mv "$RELEASE.tmp" "$RELEASE"
chown -R root:root "$RELEASE" && chmod -R go-w "$RELEASE"

if [[ ! -f /etc/printhub/printhub.env ]]; then
  install -m 0640 -g printhub "$SRC/deploy/printhub.env.example" /etc/printhub/printhub.env
  echo "Created /etc/printhub/printhub.env — review it."
fi

PREVIOUS="$(readlink -f "$PREFIX/current" 2>/dev/null || true)"
ln -sfn "$RELEASE" "$PREFIX/current.new" && mv -T "$PREFIX/current.new" "$PREFIX/current"

say "== systemd =="
install -m 0755 "$SRC/deploy/printhub-admin" /usr/local/bin/printhub-admin
install -m 0644 "$SRC/deploy/printhub.service" /etc/systemd/system/printhub.service
install -m 0644 "$SRC/deploy/printhub-backup.service" /etc/systemd/system/printhub-backup.service
install -m 0644 "$SRC/deploy/printhub-backup.timer" /etc/systemd/system/printhub-backup.timer
systemctl daemon-reload
systemctl enable --now printhub-backup.timer
systemctl enable printhub
systemctl restart printhub

say "== Health check =="
for i in $(seq 1 20); do
  curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1 && { echo "Print Hub $VERSION is running."; break; }
  sleep 1
  if [[ $i -eq 20 ]]; then
    echo "Service did not become healthy. Logs: journalctl -u printhub -n 50" >&2
    if [[ -n "$PREVIOUS" && "$PREVIOUS" != "$RELEASE" ]]; then
      echo "Rolling back to $PREVIOUS" >&2
      ln -sfn "$PREVIOUS" "$PREFIX/current"; systemctl restart printhub
    fi
    exit 1
  fi
done
/usr/local/bin/printhub-admin check || true

cat <<EOF

Next steps:
  1. Create the first administrator:   sudo printhub-admin create-admin <username>
  2. Set up the station display:  sudo $PREFIX/current/deploy/setup-station.sh <station-login-user>
  3. Restrict the firewall to the office subnet (docs/OPERATIONS.md › Network).
EOF
