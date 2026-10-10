#!/usr/bin/env bash
# Install/refresh the systemd *user* units (no sudo). Re-run after editing deploy/systemd/.
# Boot start without anyone logged in needs linger, enabled once by root:
#   sudo loginctl enable-linger administrator
set -euo pipefail
cd "$(dirname "$0")/.."
UNIT_DIR="$HOME/.config/systemd/user"
SERVICES=(decant-listener decant-parser decant-web)

mkdir -p "$UNIT_DIR"
install -m 0644 deploy/systemd/*.service deploy/systemd/*.timer "$UNIT_DIR/"
systemctl --user daemon-reload

# Stop copies started by hand with nohup (before Phase 5), so they don't run twice.
for pattern in "python -m app\.listener\.main" "python -m app\.parser\.worker" "uvicorn app\.web\.main:app"; do
  for pid in $(pgrep -u "$USER" -f "$pattern" || true); do
    unit=$(ps -o uunit= -p "$pid" 2>/dev/null || true)
    if [[ "$unit" != decant-* ]]; then
      echo "stopping hand-started process $pid ($pattern)"; kill "$pid"
    fi
  done
done
sleep 2

systemctl --user enable --now "${SERVICES[@]/%/.service}" decant-backup.timer
systemctl --user restart "${SERVICES[@]/%/.service}"   # pick up new code
systemctl --user --no-pager list-units 'decant-*' --all
echo
echo "linger: $(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo unknown) (must be 'yes' to start at boot)"
