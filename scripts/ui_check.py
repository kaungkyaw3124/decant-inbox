"""UI gate (docs/SPEC-v4.15-ui-bootstrap.md U0/U5): every page x role x language x width in a real browser.

Runs ONLY on its own database (<db_name>_uicheck) filled with fake data, never the live one.
  .venv/bin/python -m scripts.ui_check                  # full run, exit 1 on any failed check
  .venv/bin/python -m scripts.ui_check --quick          # 360 px, daily pages (tests/test_ui_check.py)
  .venv/bin/python -m scripts.ui_check --save-inventory # store the feature inventory (C7 baseline)
Screenshots: ui-shots/<page>-<role>-<lang>-<width>.png (git-ignored).
Chromium needs system libraries: `sudo bash scripts/install_ui_check_deps.sh`, or without sudo
`bash scripts/ui_check_libs.sh` (unpacks them into ~/.cache/ui-check-libs, used automatically).
"""
import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core.config import get_settings  # noqa: E402

DB = get_settings().db_name + "_uicheck"


def use_check_database() -> None:
    """Before anything opens the database: this process only ever talks to DB (fake data)."""
    os.chdir(ROOT)
    os.environ.update(DB_NAME=DB, WEB_SECRET_KEY="ui-check-only", AI_PROVIDER="off", WEB_COOKIE_SECURE="false",
                      TEST_PAY_CODE="UiCheck2468")
    get_settings.cache_clear()

SHOTS = ROOT / "ui-shots"
INVENTORY = ROOT / "tests" / "fixtures" / "ui_inventory.json"
LIBS = Path.home() / ".cache" / "ui-check-libs"
PORT = 8765
WIDTHS = (360, 768, 1280)
DAILY = ("inbox", "chats", "chat", "payments", "payment", "payment-test", "orders", "orders-test")
SKIP = {"/healthz", "/media/{message_id}", "/payments/{check_id}/shot", "/sales/export.xlsx",
        "/prices/export.xlsx", "/login"}  # files / JSON, not pages
PARTIALS = {"/messages/{message_id}/row", "/chats/{customer_id}/thread"}


# ---------- fake data ----------

def build_database() -> dict[str, int]:
    """A fresh <db>_uicheck with the shop in every state; returns the ids the page paths need."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    admin = create_engine(get_settings().database_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{DB}"'))
    admin.dispose()
    command.upgrade(Config("alembic.ini"), "head")

    from fastapi.testclient import TestClient

    from app.core.db import SessionLocal, engine
    from app.models import User
    from app.orders import testpay
    from app.parser.worker import run_batch, scan_payments
    from app.web.auth import hash_password
    from app.web.main import app
    from scripts.seed_catalog import seed
    from tests.test_cart import SAUVAGE, Y_SOLD_OUT
    from tests.test_messaging import add, customer_id, scalar
    from tests.test_payments import photo, waiting_for_payment
    from tests.test_prices import STW, run_import, xlsx
    from tests.test_seed_catalog import write_csvs
    from tests.test_web import PASSWORD, add_message, log_in

    seed(write_csvs(Path(tempfile.mkdtemp())))
    with SessionLocal.begin() as s:
        s.add(User(username="owner", password_hash=hash_password(PASSWORD), role="owner"))
        s.add(User(username="staff1", password_hash=hash_password(PASSWORD), role="staff"))
    add_message(1, "stw intensely ၅ ml ဝယ်ချင်လို့ပါ")
    add_message(2, "ကျေးဇူးပါ")
    add_message(3, "aventus 10ml ရှိလား", user_id="77")
    run_import(xlsx(STW, SAUVAGE, Y_SOLD_OUT))
    client = TestClient(app, base_url="https://testserver")
    token = log_in(client)
    client.post("/settings/payment-methods", data={"csrf": token, "name": "KPay", "account_number": "09000000001",
                                                   "account_name": "Test Shop"})
    # long Burmese text, an unknown product (learning card), a question
    add(10, "မင်္ဂလာပါရှင့် Stronger With You Intensely ၅ မီလီ နဲ့ Sauvage ၁၀ ml ကို ရန်ကုန် လှိုင်သာယာ ကို ပို့ပေးလို့ "
            "ရမလား၊ ငွေကို KPay နဲ့ လွှဲလို့ရလား၊ ဘယ်နှစ်ရက်လောက်ကြာမလဲ သိချင်ပါတယ်ရှင့်", customer="60")
    add(11, "liquid brun 5ml ယူမယ်", customer="61")
    add(12, "ပို့ခ ဘယ်လောက်လဲ", customer="62")
    run_batch()

    ids = {}
    ids["customer"] = waiting_for_payment(client, token, db=engine, customer="91")
    photo(1, customer="91")  # a real payment check (screenshot not downloaded)
    # test orders in every status: code -> test check -> approve -> packed / sent out / delivered / cancelled
    for n, external in enumerate(("92", "93", "94", "95", "96", "97")):
        cid = waiting_for_payment(client, token, db=engine, customer=external)
        client.post(f"/customers/{cid}/tester", data={"csrf": token, "on": "1"})
        add(800 + n, os.environ["TEST_PAY_CODE"], customer=external)
        run_batch()
        scan_payments()
    checks = [r for r, in engine.connect().execute(text("SELECT id FROM payment_checks WHERE is_test ORDER BY id"))]
    ids["test_check"] = checks[0]
    for check in checks[1:]:
        client.post(f"/payments/{check}/approve", data={"csrf": token})
    orders = [r for r, in engine.connect().execute(text("SELECT id FROM orders WHERE is_test AND order_no IS NOT NULL "
                                                        "ORDER BY order_no"))]
    for order_id, moves in zip(orders, ((), ("packed",), ("packed", "sent_out"), ("packed", "sent_out", "delivered"))):
        for to in moves:
            client.post(f"/orders/{order_id}/status", data={"csrf": token, "to": to, "deli_name": "Royal Express"})
    client.post(f"/orders/{orders[-1]}/cancel", data={"csrf": token, "note": "test"})
    with engine.begin() as c:  # one real paid order (approval needs a downloaded screenshot)
        c.execute(text("UPDATE outbox SET send_after = now() WHERE status = 'queued'"))
    cid = waiting_for_payment(client, token, db=engine, customer="98")
    with engine.begin() as c:
        c.execute(text("UPDATE orders SET status = 'paid', paid_at = now(), order_no = nextval('order_no_seq') "
                       "WHERE customer_id = :c"), {"c": cid})
    stw = scalar(engine, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    cart_customer = customer_id(engine, "60")
    client.post(f"/chats/{cart_customer}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "5"})
    ids["check"] = scalar(engine, "SELECT id FROM payment_checks WHERE NOT is_test ORDER BY id LIMIT 1")
    ids["product"] = stw
    ids["message"] = scalar(engine, "SELECT id FROM messages WHERE external_message_id = '10'")
    ids["practice"] = 1
    engine.dispose()
    return ids


# ---------- pages ----------

def pages(ids: dict[str, int]) -> list[tuple[str, str, bool]]:
    """(name, url, is_partial) for every GET page of the app, from the router (a new page can't be forgotten)."""
    from app.web.main import app

    fill = {"{message_id}": ids["message"], "{product_id}": ids["product"], "{customer_id}": ids["customer"],
            "{n}": ids["practice"]}
    found = []
    for route in app.routes:
        for r in [route] if hasattr(route, "methods") else getattr(getattr(route, "original_router", None), "routes", []):
            if "GET" not in (getattr(r, "methods", None) or ()) or r.path in SKIP:
                continue
            if r.path == "/payments/{check_id}":
                found += [("payment", f"/payments/{ids['check']}", False),
                          ("payment-test", f"/payments/{ids['test_check']}", False)]
                continue
            url = r.path
            for key, value in fill.items():
                url = url.replace(key, str(value))
            name = r.endpoint.__name__.removesuffix("_page").replace("_", "-")
            name = {"chat-list": "chats", "payment-list": "payments", "orders": "orders"}.get(name, name)
            found.append((name, url, r.path in PARTIALS))
    found.append(("orders-test", "/orders?tab=all&show_test=1", False))
    return found


def serve() -> None:
    import uvicorn

    from app.web.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.1)


# ---------- checks (run in the page) ----------

CHECKS_JS = r"""(args) => {
  const [width, lang] = args;
  const out = {c2: [], c3: [], c4: [], c5: [], c6: []};
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const label = el => (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + ' "' +
    (el.innerText || el.value || el.name || el.getAttribute('aria-label') || '').trim().slice(0, 40) + '"');
  // C2 no sideways page scroll
  if (document.documentElement.scrollWidth > innerWidth + 1)
    out.c2.push(`page ${document.documentElement.scrollWidth}px wide in ${innerWidth}px`);
  // C3 tap size on phones: buttons, inputs and links that stand alone (links inside a sentence are exempt)
  if (width <= 360) {
    const main = document.querySelector('main') || document.body;
    for (const el of main.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, summary')) {
      if (!vis(el) || el.closest('.help p, .tap-exempt')) continue;
      let box = el;
      if (el.matches('input[type=checkbox], input[type=radio]')) box = el.closest('label') || el;
      if (el.tagName === 'A') {
        const p = el.parentElement; const own = [...p.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim());
        if (own.length && getComputedStyle(el).display === 'inline') continue;
      }
      const h = box.getBoundingClientRect().height;
      if (h < 39.5) out.c3.push(`${label(el)} ${Math.round(h)}px`);
    }
  }
  // C4 CSRF on every POST form, CSRF header for HTMX
  for (const f of document.querySelectorAll('form')) {
    if ((f.getAttribute('method') || 'get').toLowerCase() === 'post' && !f.querySelector('input[name=csrf]'))
      out.c4.push(`form ${f.getAttribute('action')} has no csrf`);
  }
  if (document.querySelector('[hx-post], [hx-get]')) {
    const h = document.body.getAttribute('hx-headers') || '';
    if (!/X-CSRF-Token":\s*"[^"]+/.test(h)) out.c4.push('hx-headers without X-CSRF-Token');
  }
  // C5 contrast (WCAG AA) for body text, buttons and badges
  const rgb = c => (c.match(/[\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const bg = el => { for (let e = el; e; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor);
      if (c.length === 3 || (c.length === 4 && c[3] > .5)) return c.slice(0, 3); } return [255, 255, 255]; };
  const targets = [document.body, ...document.querySelectorAll('button, .btn, .badge, a.button, summary.button')];
  for (const el of targets) {
    if (!vis(el) || !(el.innerText || '').trim() || el.closest('[disabled], .disabled')) continue;
    const s = getComputedStyle(el); const fg = rgb(s.color).slice(0, 3);
    const a = lum(fg), b = lum(bg(el)); const ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    const large = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.6 && +s.fontWeight >= 700);
    if (ratio < (large ? 3 : 4.5)) out.c5.push(`${label(el)} ${ratio.toFixed(2)}`);
  }
  // C6 Burmese: nothing clipped in buttons, badges, nav items
  if (lang === 'my') {
    for (const el of document.querySelectorAll('button, .btn, .badge, nav a, .nav-link, .tabbar a')) {
      if (vis(el) && el.scrollHeight > el.clientHeight + 1 && el.clientHeight > 0)
        out.c6.push(`${label(el)} ${el.scrollHeight}>${el.clientHeight}`);
    }
  }
  return out;
}"""

INVENTORY_JS = r"""() => {
  const items = new Set();
  const path = u => { try { const x = new URL(u, location.href); return x.pathname + x.search; } catch { return u; } };
  for (const f of document.querySelectorAll('form')) {
    const names = [...new Set([...f.querySelectorAll('[name]')].map(e => e.name).filter(n => n !== 'csrf'))].sort();
    items.add(`form ${(f.getAttribute('method') || 'get').toLowerCase()} ${path(f.getAttribute('action') || '')} [${names}]`);
  }
  for (const b of document.querySelectorAll('button[name]')) items.add(`button ${b.name}=${b.value}`);
  for (const a of document.querySelectorAll('a[href]')) {
    const h = a.getAttribute('href'); if (!h.startsWith('#') && !h.startsWith('javascript')) items.add(`link ${path(h)}`);
  }
  for (const e of document.querySelectorAll('[hx-get], [hx-post]'))
    items.add(`hx ${e.getAttribute('hx-get') || e.getAttribute('hx-post')} -> ${e.getAttribute('hx-target') || ''}`);
  return [...items].sort();
}"""


def libs_env() -> dict[str, str] | None:
    if not (LIBS / "root").exists():
        return None
    return {**os.environ, "LD_LIBRARY_PATH": str(LIBS / "root/usr/lib/x86_64-linux-gnu"),
            "FONTCONFIG_FILE": str(LIBS / "fonts.conf")}


def log_in(page, username: str) -> None:
    from tests.test_web import PASSWORD

    page.goto(f"http://127.0.0.1:{PORT}/login")
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", PASSWORD)
    page.locator("form[action='/login'] button").first.click()
    page.wait_for_load_state()


def set_language(page, lang: str) -> None:
    token = page.locator("input[name=csrf]").first.get_attribute("value")
    page.request.post(f"http://127.0.0.1:{PORT}/language", form={"csrf": token, "language": lang, "back": "/"})


# volatile parts of the inventory: per-request keys and ages differ between runs
VOLATILE = re.compile(r"(expect=|key=)[^ ]*|[?&]t=\d+")


def run(quick: bool, save_inventory: bool) -> int:
    from playwright.sync_api import sync_playwright

    use_check_database()
    ids = build_database()
    serve()
    SHOTS.mkdir(exist_ok=True)
    targets = pages(ids)
    if quick:
        targets = [t for t in targets if t[0] in DAILY]
    widths, langs = ((360,), ("my", "en")) if quick else (WIDTHS, ("en", "my"))
    failures, inventory, lines = 0, {}, []
    with sync_playwright() as p:
        browser = p.chromium.launch(env=libs_env())
        for role, username in (("owner", "owner"), ("staff", "staff1")):
            context = browser.new_context()
            page = context.new_page()
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            if role == "owner":  # the login page, before logging in
                for width in widths:
                    page.set_viewport_size({"width": width, "height": 800})
                    page.goto(f"http://127.0.0.1:{PORT}/login")
                    page.screenshot(path=SHOTS / f"login-{width}.png", full_page=True)
                    for check, problems in sorted(page.evaluate(CHECKS_JS, [width, "my"]).items()):
                        if problems:
                            failures += 1
                            lines.append(f"FAIL {check.upper()} login {width}: " + "; ".join(problems[:6]))
            log_in(page, username)
            for lang in langs:
                set_language(page, lang)
                for width in widths:
                    page.set_viewport_size({"width": width, "height": 800})
                    for name, url, partial in targets:
                        errors.clear()
                        response = page.goto(f"http://127.0.0.1:{PORT}{url}")
                        status = response.status if response else 0
                        key = f"{name}-{role}"
                        if lang == "en" and width == widths[-1]:
                            inventory[key] = ([f"status {status}"] + [VOLATILE.sub(r"\1", i) for i in
                                              page.evaluate(INVENTORY_JS)]) if status == 200 else [f"status {status}"]
                        if status == 403 and role == "staff":
                            continue  # owner-only page: the inventory keeps the 403 (C7 checks it stays)
                        found = {"c1": ([f"HTTP {status}"] if status != 200 else []) + errors[:3]}
                        if not partial:
                            page.wait_for_function("document.fonts.status === 'loaded'")
                            page.screenshot(path=SHOTS / f"{name}-{role}-{lang}-{width}.png", full_page=True)
                            found |= page.evaluate(CHECKS_JS, [width, lang])
                        for check, problems in sorted(found.items()):
                            if problems:
                                failures += 1
                                lines.append(f"FAIL {check.upper()} {name} {role} {lang} {width}: "
                                             + "; ".join(problems[:6]) + (f" (+{len(problems) - 6})" if len(problems) > 6 else ""))
            context.close()
        browser.close()

    if save_inventory:
        INVENTORY.write_text(json.dumps(inventory, indent=1, ensure_ascii=False) + "\n")
        print(f"saved {INVENTORY.relative_to(ROOT)} ({len(inventory)} pages)")
    elif INVENTORY.exists():  # C7: nothing that existed before is gone (same role)
        old = json.loads(INVENTORY.read_text())
        for key, items in inventory.items():
            missing = sorted(set(old.get(key, [])) - set(items))
            if missing:
                failures += 1
                lines.append(f"FAIL C7 {key}: missing " + " | ".join(missing[:8]) + (f" (+{len(missing) - 8})" if len(missing) > 8 else ""))
    print("\n".join(lines))
    checked = len(targets) * len(widths) * len(langs) * 2
    print(f"{'PASS' if not failures else 'FAIL'}: {checked} page views, {failures} failed checks; screenshots in ui-shots/")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--save-inventory", action="store_true")
    args = parser.parse_args()
    sys.exit(run(args.quick, args.save_inventory))
