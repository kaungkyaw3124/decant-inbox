"""docs/SPEC-v5.5-layout-hotfix.md: pages centred and using the width on a wide PC; login centred (L1-L6)."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_ui_check import _browser_ok

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "app/web/static/app.css").read_text()


def test_l4_one_page_container():
    """One .page rule; no old left-glued or per-page main widths left."""
    assert '<main class="{% block main_class %}page{% endblock %}">' in (ROOT / "app/web/templates/base.html").read_text()
    assert not re.search(r"(^|\s)main(\.wide|:not\([^)]*\))?\s*\{[^}]*max-width", CSS, re.M)
    assert "main.wide" not in CSS and "margin: 0; max-width: 1200px" not in CSS
    assert "max-width: min(1440px, 100% - 80px)" in CSS and "max-width: min(1680px, 100% - 80px)" in CSS
    # only the Chats workspace replaces the container
    users = [p.name for p in (ROOT / "app/web/templates").glob("*.html") if "block main_class" in p.read_text()]
    assert sorted(users) == ["base.html", "chat.html", "chats.html", "inbox.html"]


@pytest.mark.skipif(not _browser_ok(), reason="headless Chromium cannot start here: bash scripts/ui_check_libs.sh")
def test_l6_c8_centred_on_wide_screens():
    """C8 at 1440 / 1920 / 2560 px on the list pages + login (the full gate checks every page)."""
    run = subprocess.run([sys.executable, "-m", "scripts.ui_check", "--widths", "1280",
                          "--pages", "products,customers,orders,settings,ai,chats"],
                         cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-2000:]
    assert "PASS:" in run.stdout
    for name in ("login-1440", "products-1920", "settings-2560"):
        assert (ROOT / f"ui-shots/5.5/{name}.png").exists()
