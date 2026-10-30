#!/usr/bin/env bash
# No-sudo alternative to install_ui_check_deps.sh: unpacks the libraries headless Chromium needs into
# ~/.cache/ui-check-libs (scripts/ui_check.py uses them automatically). Usage: bash scripts/ui_check_libs.sh
set -euo pipefail
L="$HOME/.cache/ui-check-libs"
mkdir -p "$L/debs" && cd "$L/debs"
apt-get download libatk1.0-0t64 libatk-bridge2.0-0t64 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
  libasound2t64 libatspi2.0-0t64 libxrender1 libxi6 libxres1 libfontconfig1 fontconfig-config \
  fonts-noto-color-emoji fonts-dejavu-core
for d in *.deb; do dpkg-deb -x "$d" "$L/root"; done
cat > "$L/fonts.conf" <<CONF
<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig><dir>$L/root/usr/share/fonts</dir><cachedir>$L/fccache</cachedir></fontconfig>
CONF
echo "ok: $L"
