#!/usr/bin/env bash
# docs/SPEC-v5.3-performance-pc.md M4: Claude Code's test runs must not slow the live shop.
# Lowest CPU + disk priority, 1 pytest worker (pytest.ini). Same for the UI gate and the simulator:
#   bash scripts/test.sh                      # full pytest suite
#   bash scripts/test.sh tests/test_web.py    # some tests
#   nice -n 19 ionice -c3 .venv/bin/python -m scripts.ui_check --quick
#   nice -n 19 ionice -c3 .venv/bin/python -m scripts.simulate
cd "$(dirname "$0")/.."
exec nice -n 19 ionice -c3 .venv/bin/python -m pytest -q "$@"
