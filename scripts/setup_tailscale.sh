#!/usr/bin/env bash
# Install Tailscale and publish the dashboard (127.0.0.1:8080) privately on the tailnet
# over HTTPS. Run once, as root:   sudo bash scripts/setup_tailscale.sh
#
# What it does:
#   1. adds Tailscale's signed apt repo for this Ubuntu release and installs tailscale
#   2. `tailscale up` -> prints a login URL; open it and log in with YOUR Tailscale account
#   3. `tailscale serve` -> https://<hostname>.<tailnet>.ts.net/ -> http://127.0.0.1:8080
#      (if HTTPS certificates are off for the tailnet, it prints a link to enable them)
# What it does NOT do: open any public port, enable Tailscale SSH, or change ufw
# (ufw already allows traffic on tailscale0).
set -euo pipefail

OPERATOR="${SUDO_USER:-administrator}"   # may run `tailscale serve/status` later without sudo
HOSTNAME_TS="decant-inbox"

[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo bash $0" >&2; exit 1; }
. /etc/os-release
echo "== Ubuntu ${VERSION_ID} (${VERSION_CODENAME}), operator: ${OPERATOR}"

if ! command -v tailscale >/dev/null; then
  echo "== Installing Tailscale from pkgs.tailscale.com (${VERSION_CODENAME})"
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.noarmor.gpg" \
    -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.tailscale-keyring.list" \
    -o /etc/apt/sources.list.d/tailscale.list
  apt-get update -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/tailscale.list \
    -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0
  DEBIAN_FRONTEND=noninteractive apt-get install -y tailscale
else
  echo "== Tailscale already installed: $(tailscale version | head -1)"
fi
systemctl enable --now tailscaled

echo "== Logging in: open the URL below in a browser and approve this machine"
tailscale up --hostname="${HOSTNAME_TS}" --operator="${OPERATOR}" --ssh=false

echo "== Publishing the dashboard on the tailnet (HTTPS 443 -> 127.0.0.1:8080)"
tailscale serve --bg --https=443 http://127.0.0.1:8080

echo
tailscale serve status
echo
echo "Done. Install the Tailscale app on your phone and laptop, log in with the same"
echo "account, then open the https://${HOSTNAME_TS}.<your-tailnet>.ts.net address above."
command -v ufw >/dev/null && ufw status | grep -q tailscale0 \
  || echo "WARNING: no ufw rule for tailscale0 found; check 'ufw status'."
