#!/usr/bin/env bash
# Keep the station available: no suspend on idle or lid close while on AC power.
# Review before running; every change is printed and reversible (see --show).
#
#   sudo ./station-power.sh <station-user>          # apply
#   sudo ./station-power.sh <station-user> --show   # print current values only
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
USER_NAME="${1:?usage: station-power.sh <station-user> [--show]}"
UID_N="$(id -u "$USER_NAME")"
as_user() { sudo -u "$USER_NAME" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_N/bus" "$@"; }

KEYS=(
  "org.cinnamon.settings-daemon.plugins.power sleep-inactive-ac-timeout 0"
  "org.cinnamon.settings-daemon.plugins.power lid-close-ac-action nothing"
  "org.cinnamon.settings-daemon.plugins.power sleep-display-ac 1800"
  "org.cinnamon.desktop.session idle-delay 0"
  "org.cinnamon.desktop.screensaver lock-enabled false"
)

echo "Current values:"
for k in "${KEYS[@]}"; do set -- $k; printf '  %s %s = %s\n' "$1" "$2" "$(as_user gsettings get "$1" "$2" 2>/dev/null || echo n/a)"; done
echo "logind HandleLidSwitchExternalPower: $(grep -h '^HandleLidSwitchExternalPower' /etc/systemd/logind.conf /etc/systemd/logind.conf.d/*.conf 2>/dev/null || echo default)"
[[ "${2:-}" == --show ]] && exit 0

for k in "${KEYS[@]}"; do set -- $k; as_user gsettings set "$1" "$2" "$3" && echo "set $1 $2 $3"; done
# The display may sleep after 30 min; the service keeps running regardless.
install -d /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/printhub-station.conf <<'EOF'
# Print Hub station: do not suspend when the lid is closed on AC power.
[Login]
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
EOF
echo "Wrote /etc/systemd/logind.conf.d/printhub-station.conf (takes effect after reboot or 'systemctl restart systemd-logind', which ends the graphical session)."
echo "Screen lock is disabled for the station user because the hub has its own sign-in and idle sign-out. Revert with: gsettings reset <schema> <key>."
