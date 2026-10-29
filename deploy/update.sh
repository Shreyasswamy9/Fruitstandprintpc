#!/usr/bin/env bash
# Update Print Hub to a new release, with automatic rollback.
#
#   sudo ./update.sh /path/to/printhub-<version>.tar.gz
#   sudo ./update.sh --rollback          # switch back to the previous release
#
# Steps: back up the database -> unpack -> install side by side -> switch the
# `current` symlink -> restart -> health check. If the health check fails, the
# previous release and the pre-update database backup are restored.
set -euo pipefail
PREFIX=/opt/printhub
[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

run_cli() { /usr/local/bin/printhub-admin "$@"; }
healthy() { for _ in $(seq 1 20); do curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

if [[ "${1:-}" == "--rollback" ]]; then
  CUR="$(readlink -f $PREFIX/current)"
  PREV="$(ls -1dt $PREFIX/releases/*/ | sed 's:/$::' | grep -vx "$CUR" | head -1)"
  [[ -n "$PREV" ]] || { echo "No previous release found." >&2; exit 1; }
  echo "Rolling back: $CUR -> $PREV"
  ln -sfn "$PREV" "$PREFIX/current"; systemctl restart printhub
  healthy && echo "Rolled back." || { echo "Still unhealthy — see journalctl -u printhub" >&2; exit 1; }
  echo "If the newer release changed the database, restore the pre-update backup: see docs/OPERATIONS.md › Restore."
  exit 0
fi

TARBALL="${1:?usage: update.sh <release.tar.gz> | --rollback}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

echo "== Backing up database"
BACKUP="$(run_cli backup /var/lib/printhub/backups | tail -1)"
echo "Backup: $BACKUP"

echo "== Unpacking $TARBALL"
tar -C "$WORK" -xzf "$TARBALL"
SRC="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -1)"
PREVIOUS="$(readlink -f $PREFIX/current)"

if ! "$SRC/deploy/install.sh" --yes; then
  echo "== Update failed; restoring previous release and database" >&2
  systemctl stop printhub
  ln -sfn "$PREVIOUS" "$PREFIX/current"
  run_cli restore "$BACKUP" --yes
  systemctl start printhub
  healthy && echo "Previous release restored." >&2
  exit 1
fi
echo "Updated to $(readlink -f $PREFIX/current). Previous release kept at $PREVIOUS."
# Keep the three most recent releases.
ls -1dt $PREFIX/releases/*/ | tail -n +4 | xargs -r rm -rf
