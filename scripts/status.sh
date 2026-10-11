#!/usr/bin/env bash
# One-screen status: services, health checks, newest backup, public dashboard address.
# Usage (over SSH): ~/telegram-product-requests/scripts/status.sh
cd "$(dirname "$0")/.."
echo "== services"
systemctl --user --no-pager --no-legend list-units 'decant-*' --all | awk '{printf "  %-26s %s %s\n", $1, $3, $4}'
echo "  linger: $(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo unknown) (yes = starts at boot)"
echo "== health (/healthz)"
curl -s --max-time 5 http://127.0.0.1:8080/healthz | sed 's/^/  /' || echo "  web not answering"
echo
echo "== newest backup"
newest=$(ls -t backups/*.dump 2>/dev/null | head -1)
if [[ -n "$newest" ]]; then echo "  $(basename "$newest") ($(du -h "$newest" | cut -f1))"; else echo "  none yet"; fi
echo "== dashboard"
if [[ -s TUNNEL_URL ]]; then echo "  public:   $(cat TUNNEL_URL)"; else echo "  public:   no tunnel URL yet (journalctl --user -u decant-tunnel -n 30)"; fi
echo "  fallback: ssh -p 10066 -L 8080:127.0.0.1:8080 administrator@93.127.132.69, then http://localhost:8080"
