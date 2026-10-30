"""docs/SPEC-v4.15-ui-bootstrap.md U5: the phone layout gate stays green, and pages stay light."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "web" / "static"


def test_page_weight_under_400_kb():
    base = (ROOT / "app/web/templates/base.html").read_text()
    assets = re.findall(r'(?:href|src)="/static/([^"]+\.(?:css|js))"', base)
    assert len(assets) >= 6 and not any("cdn" in a for a in assets)  # everything self-hosted
    total = sum((STATIC / a).stat().st_size for a in assets)
    assert total < 400_000, f"{total} bytes of CSS + JS per page"


def test_vendored_licences_and_versions():
    vendor = STATIC / "vendor"
    for folder in ("bootstrap-5.3.8", "bootstrap-icons-1.13.1", "noto-sans-myanmar-5.3.0"):
        assert (vendor / folder / "LICENSE").exists(), folder
    assert "SIL Open Font License" in (vendor / "noto-sans-myanmar-5.3.0/LICENSE").read_text()
    assert "htmx-2.0.4.min.js" in (ROOT / "app/web/templates/base.html").read_text()


def _browser_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        from scripts.ui_check import libs_env
        with sync_playwright() as p:
            p.chromium.launch(env=libs_env()).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _browser_ok(), reason="headless Chromium cannot start here: bash scripts/ui_check_libs.sh")
def test_ui_check_quick_daily_pages_on_a_phone():
    """360 px, Burmese + English, owner + staff, the daily pages: C1-C7 all pass."""
    run = subprocess.run([sys.executable, "-m", "scripts.ui_check", "--quick"], cwd=ROOT, capture_output=True,
                         text=True, timeout=900)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-2000:]
    assert "PASS:" in run.stdout
