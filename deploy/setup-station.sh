#!/usr/bin/env bash
# Configure the on-site station account to open the dashboard after login.
#
#   sudo ./setup-station.sh <station-user>            # maximized app window
#   sudo ./setup-station.sh <station-user> --kiosk    # full-screen kiosk
#   sudo ./setup-station.sh <station-user> --remove   # undo
#
# Only touches the station user's ~/.config/autostart, ~/.config/printhub and
# the applications menu entry. Power settings are separate (station-power.sh).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
USER_NAME="${1:?usage: setup-station.sh <station-user> [--kiosk|--remove]}"
OPT="${2:-}"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
[[ -n "$HOME_DIR" ]] || { echo "No such user: $USER_NAME" >&2; exit 1; }
SRC="$(cd "$(dirname "$0")" && pwd)"

if [[ "$OPT" == --remove ]]; then
  rm -f "$HOME_DIR/.config/autostart/printhub.desktop" /usr/share/applications/printhub.desktop
  echo "Autostart removed for $USER_NAME."
  exit 0
fi

install -m 0755 "$SRC/printhub-kiosk" /usr/local/bin/printhub-kiosk
install -m 0644 "$SRC/printhub.desktop" /usr/share/applications/printhub.desktop
sudo -u "$USER_NAME" mkdir -p "$HOME_DIR/.config/autostart" "$HOME_DIR/.config/printhub"
sudo -u "$USER_NAME" install -m 0644 "$SRC/printhub.desktop" "$HOME_DIR/.config/autostart/printhub.desktop"
MODE=window; [[ "$OPT" == --kiosk ]] && MODE=kiosk
sudo -u "$USER_NAME" tee "$HOME_DIR/.config/printhub/station.conf" >/dev/null <<EOF
# Print Hub station display. window = maximized app window, kiosk = full screen.
PRINTHUB_DISPLAY=$MODE
PRINTHUB_URL=http://127.0.0.1:8080/
EOF
echo "Station user $USER_NAME will open Print Hub ($MODE) at login."
command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || \
  echo "Note: Chromium is recommended for the app-window mode (sudo apt install chromium). Firefox works as a fallback."
