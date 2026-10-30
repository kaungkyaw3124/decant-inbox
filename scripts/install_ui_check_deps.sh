#!/usr/bin/env bash
# One-time, needs sudo (docs/SPEC-v4.15-ui-bootstrap.md U0): system libraries + fonts for the headless
# Chromium that scripts/ui_check.py uses for screenshots. Usage: sudo bash scripts/install_ui_check_deps.sh
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/playwright install-deps chromium
