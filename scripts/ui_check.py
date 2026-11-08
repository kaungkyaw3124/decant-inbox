"""UI gate (docs/SPEC-v4.15-ui-bootstrap.md U0/U5): every page x role x language x width in a real browser.

Runs ONLY on its own database (<db_name>_uicheck) filled with fake data, never the live one.
  .venv/bin/python -m scripts.ui_check                  # full run, exit 1 on any failed check
  .venv/bin/python -m scripts.ui_check --quick          # 360 px, daily pages (tests/test_ui_check.py)
  .venv/bin/python -m scripts.ui_check --save-inventory # store the feature inventory (C7 baseline)
Screenshots: ui-shots/<page>-<role>-<lang>-<width>.png, wide-PC ones (C8) in ui-shots/5.5/ (git-ignored).
Chromium needs system libraries: `sudo bash scripts/install_ui_check_deps.sh`, or without sudo
`bash scripts/ui_check_libs.sh` (unpacks them into ~/.cache/ui-check-libs, used automatically).
"""
import argparse
from datetime import UTC, datetime
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
        "/prices/export.xlsx", "/login", "/stock/export.xlsx", "/customers/export.csv",
        "/events"}  # files / JSON / the live stream, not pages
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
    from app.inventory import stock as inventory  # docs/SPEC-v5.6: counted perfumes in every stock state
    sauvage = scalar(engine, "SELECT id FROM products WHERE name = 'Sauvage Eau de Parfum'")
    with SessionLocal.begin() as s:
        inventory.add_bottles(s, stw, 100, 1, 250000, None, None)
        inventory.add_bottles(s, stw, 100, 1, 250000, 60.5, None)
        inventory.add_bottles(s, sauvage, 100, 1, 300000, 6, None)
    from scripts.perf_check import seed_long_chat  # docs/SPEC-v5.7 D2/D3: a 600-message chat
    with SessionLocal.begin() as s:
        ids["long"] = seed_long_chat(s, "ui-long", end=datetime(2026, 1, 1, tzinfo=UTC))  # older than the other test messages
    ids["low"] = sauvage
    ids["untracked"] = scalar(engine, "SELECT id FROM products WHERE name = 'Y Eau de Parfum'")
    ids["practice"] = 1
    ids["order"] = orders[0]  # a paid test order (packing slip)
    engine.dispose()
    return ids


# ---------- pages ----------

def pages(ids: dict[str, int]) -> list[tuple[str, str, bool]]:
    """(name, url, is_partial) for every GET page of the app, from the router (a new page can't be forgotten)."""
    from app.web.main import app

    fill = {"{message_id}": ids["message"], "{product_id}": ids["product"], "{customer_id}": ids["customer"],
            "{n}": ids["practice"], "{order_id}": ids["order"]}
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
    found.append(("chat-long", f"/chats/{ids['long']}", False))  # docs/SPEC-v5.7: the light chat
    found.append(("orders-range", "/orders?tab=all&range=7d", False))
    for tab in ("prices", "stock", "nicks"):  # docs/SPEC-v5.6: the side panel and the owner's dialogs
        found.append((f"products-{tab}", f"/products?open={ids['product']}&tab={tab}", False))
    found += [("products-untracked", f"/products?open={ids['untracked']}&tab=stock", False),
              ("products-low", f"/products?need=1&open={ids['low']}&tab=stock", False)]
    found += [(f"products-dialog-{d}", f"/products?dialog={d}", False) for d in ("add", "prices", "stock-count", "vials")]
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
  // S2 (docs/SPEC-v5.6): Products shows <= 2 buttons above the list and <= 2 per panel tab (nickname × excluded)
  if (location.pathname === '/products') {
    out.s2 = [];
    const buttons = root => [...root.querySelectorAll('button, a.button, summary.button')]
      .filter(b => vis(b) && !b.matches('.chip-x') && !b.closest('.dialog, .pager, .panel-foot')
        && !(b.closest('details:not([open])') && !b.matches('details:not([open]) > summary')));  // closed = hidden
    const head = document.querySelector('main .page-head');
    if (head && buttons(head).length > 2) out.s2.push(`${buttons(head).length} buttons above the list`);
    for (const pane of document.querySelectorAll('#panel .pane:not([hidden])'))
      if (buttons(pane).length > 2) out.s2.push(`${buttons(pane).length} buttons in ${pane.id}`);
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

# C8 (docs/SPEC-v5.5 L6): on a wide PC the page box is centred in the area next to the menu and uses the width;
# header, search, list card and pager share its left and right edges. The login card is centred in the window.
C8_WIDTHS = (1440, 1920, 2560)
C8_SHOTS = ("products", "customers", "orders", "settings", "ai")
C8_JS = r"""() => {
  const out = [];
  const main = document.querySelector('main');
  if (!main || main.classList.contains('ws-main')) return out;  // the Chats workspace is full width (L5)
  const r = main.getBoundingClientRect(), area = main.parentElement.getBoundingClientRect();
  const ps = getComputedStyle(main.parentElement);
  const left = area.left + parseFloat(ps.paddingLeft), right = area.right - parseFloat(ps.paddingRight);
  const gapL = r.left - left, gapR = right - r.right;
  if (Math.abs(gapL - gapR) > 2) out.push(`not centred: ${Math.round(gapL)}px left, ${Math.round(gapR)}px right`);
  const max = parseFloat(getComputedStyle(main).maxWidth);
  if (r.width < 0.7 * (right - left) && Math.abs(r.width - max) > 1)
    out.push(`only ${Math.round(r.width)}px of ${Math.round(right - left)}px`);
  const login = document.querySelector('.login');
  if (login) {
    const c = login.getBoundingClientRect();
    if (Math.abs(c.left + c.width / 2 - innerWidth / 2) > 2) out.push(`login card centre ${Math.round(c.left + c.width / 2)} of ${innerWidth}`);
    if (c.top + c.height / 2 > innerHeight / 2) out.push(`login card too low (${Math.round(c.top)}px)`);
  } else {
    const ms = getComputedStyle(main), inL = r.left + parseFloat(ms.paddingLeft), inR = r.right - parseFloat(ms.paddingRight);
    for (const el of main.querySelectorAll(':scope > .page-head, :scope > .toolbar, :scope > form.toolbar, :scope > .list-card')) {
      const e = el.getBoundingClientRect();
      if (e.width && (Math.abs(e.left - inL) > 2 || Math.abs(e.right - inR) > 2))
        out.push(`${el.className.split(' ')[0]} edges ${Math.round(e.left)}-${Math.round(e.right)}, page ${Math.round(inL)}-${Math.round(inR)}`);
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


def pc_flows(browser) -> list[str]:
    """docs/SPEC-v5.3-performance-pc.md M2/M3/M6 on a PC (1440 px): menu clicks swap the page without a reload,
    back works, hover prefetches (GET only) and the click uses it, the reply bubble shows at once (and turns red
    with "Try again" on an error), a new customer message appears live (SSE), arrow keys switch chats,
    nothing in localStorage. Runs before u4_flows (it sends one reply in the fake shop)."""
    from sqlalchemy import create_engine, text

    problems = []
    base = f"http://127.0.0.1:{PORT}"
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    log_in(page, "owner")
    set_language(page, "en")
    requests: list[tuple[str, str]] = []
    page.on("request", lambda r: requests.append((r.method, r.url.removeprefix(base))))

    def check(name: str, ok) -> None:
        try:
            if not ok():
                problems.append(f"PC {name}: failed ({page.url})")
        except Exception as exc:
            problems.append(f"PC {name}: {str(exc).splitlines()[0]}")

    def no_reload_to(href: str) -> bool:
        page.evaluate("window.stayed = 1")
        page.locator(f"nav.sidebar a.side-item[href='{href}']").click()
        page.wait_for_url(f"**{href}")
        page.wait_for_load_state()
        return page.evaluate("window.stayed") == 1 and page.locator("main").count() == 1

    page.goto(f"{base}/chats")
    check("menu click without reload", lambda: no_reload_to("/orders") and no_reload_to("/payments"))
    check("back button", lambda: (page.go_back(), page.wait_for_selector(
        "nav.sidebar a[href='/orders'][aria-current=page]"), page.url.endswith("/orders"))[-1])
    check("no customer pages in localStorage", lambda: page.evaluate("Object.keys(localStorage).length") == 0)

    page.goto(f"{base}/chats")
    row = page.locator("a.chatrow").nth(1)
    href = row.get_attribute("href")
    requests.clear()
    row.hover()
    page.wait_for_timeout(600)
    check("hover prefetches once with GET", lambda: requests.count(("GET", href)) == 1
          and not any(m != "GET" for m, _ in requests))
    page.evaluate("window.stayed = 1")
    row.click()
    page.wait_for_url(f"**{href}")
    page.wait_for_selector(f"#ws[data-customer='{href.rsplit('/', 1)[1]}']")
    check("click uses the prefetched page", lambda: requests.count(("GET", href)) == 1
          and page.evaluate("window.stayed") == 1)

    db = create_engine(get_settings().database_url)
    with db.connect() as c:
        cid = c.execute(text("SELECT customer_id FROM messages WHERE direction = 'in' GROUP BY customer_id "
                             "ORDER BY max(id) DESC LIMIT 1")).scalar()
    page.goto(f"{base}/chats/{cid}")
    for _ in range(50):  # (no wait_for_function: it needs eval, which our CSP blocks)
        if page.evaluate("window.decantLive === true"):
            break
        page.wait_for_timeout(100)
    with db.begin() as c:
        c.execute(text("INSERT INTO messages (channel, external_chat_id, external_message_id, customer_id, raw_text, "
                       "normalized_text, received_at, direction, kind) SELECT channel, external_chat_id, 'live-1', customer_id, "
                       "'live update check', 'live update check', now(), 'in', 'text' FROM messages "
                       "WHERE customer_id = :c LIMIT 1"), {"c": cid})
    check("new message appears live (SSE)", lambda: page.locator("#thread", has_text="live update check")
          .wait_for(timeout=6000) is None)

    page.route("**/send", lambda route: (page.wait_for_timeout(1500), route.continue_()))
    page.fill("form.compose-box textarea[name=text]", "optimistic check")
    page.evaluate("document.querySelector('form.compose-box').dataset.old = '1'")
    page.locator("form.compose-box button.send-round").click()
    check("reply bubble at once", lambda: page.locator(".bubble.optimistic", has_text="optimistic check")
          .wait_for(timeout=300) is None)
    check("bubble replaced by the real outbox row", lambda: page.locator(".bubble.pending:not(.optimistic)",
                                                                          has_text="optimistic check").wait_for() is None)
    page.wait_for_selector("form.compose-box:not([data-old])")  # the workspace swap is done (SSE may be faster)
    page.unroute("**/send")
    page.route("**/send", lambda route: route.fulfill(status=500, body="boom"))
    page.fill("form.compose-box textarea[name=text]", "error check")
    page.locator("form.compose-box button.send-round").click()
    check("error -> red bubble with Try again", lambda: page.locator(".bubble.optimistic.status-failed button",
                                                                     has_text="Try again").wait_for() is None)
    page.unroute("**/send")

    page.goto(f"{base}/chats/{cid}")
    page.locator("body").click(position={"x": 700, "y": 5})
    first = page.url
    page.keyboard.press("ArrowDown")
    check("arrow key opens the next chat", lambda: (page.wait_for_url(lambda url: url != first), True)[1])
    page.keyboard.press("?")
    check("? shows the shortcuts", lambda: page.locator("#keys.show").wait_for() is None)
    db.dispose()
    context.close()
    return problems


def u4_flows(browser) -> list[str]:
    """docs/SPEC-v4.21 U4: the owner's daily jobs in <= 3 taps on a phone (390 px), starting from any page.
    Runs last: it changes the fake shop (sends a reply, approves the test payment, packs an order)."""
    problems = []
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    log_in(page, "owner")
    set_language(page, "en")  # the selectors below read English labels
    base = f"http://127.0.0.1:{PORT}"

    def flow(name: str, taps: list[str], done) -> None:
        page.goto(f"{base}/help")  # anywhere
        try:
            for selector in taps:
                page.locator(selector).first.click()
                page.wait_for_load_state()
            if not done():
                problems.append(f"U4 {name}: no result after {len(taps)} taps ({page.url})")
        except Exception as exc:  # a missing button = the flow takes more taps
            problems.append(f"U4 {name}: {str(exc).splitlines()[0]}")

    from sqlalchemy import create_engine, text

    db = create_engine(get_settings().database_url)

    def count(sql: str) -> int:
        with db.connect() as c:
            return c.execute(text(sql)).scalar()

    sent = count("SELECT count(*) FROM outbox")
    flow("send the suggested reply", [".tabbar a[href='/chats']", ".chatrow.needs:has(.chatrow-last:text('liquid brun'))",
                                      ".needs-panel form.teach button.primary.big:not([formaction])"],
         lambda: count("SELECT count(*) FROM outbox") > sent)
    flow("approve a payment", [".tabbar a[href='/payments']", "a.row-main:has-text('TEST')", "button.approve"],
         lambda: count("SELECT count(*) FROM payment_checks WHERE is_test AND decision = 'approved'") >= 6)
    packed = count("SELECT count(*) FROM orders WHERE status = 'packed'")
    flow("mark an order packed", [".tabbar a[href='/orders']", "form[action$='/status'] button.primary"],
         lambda: count("SELECT count(*) FROM orders WHERE status = 'packed'") > packed)
    db.dispose()
    context.close()
    return problems


def s1_flows(browser) -> list[str]:
    """docs/SPEC-v5.6 S1: the owner's daily product jobs in <= 3 clicks from the Products page (PC, 1440 px), typing
    not counted; staff see the panel read-only; Esc closes the panel. Runs after u4_flows (it changes the shop)."""
    from sqlalchemy import create_engine, text

    problems, base = [], f"http://127.0.0.1:{PORT}"
    db = create_engine(get_settings().database_url)

    def value(sql: str):
        with db.connect() as c:
            return c.execute(text(sql)).scalar()

    stw = value("SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    row = f"#product-list .list-row:has(a.name:text-is('Stronger With You Intensely'))"
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    log_in(page, "owner")
    set_language(page, "en")

    def flow(name: str, steps: list, done) -> None:
        """steps: a selector = one click; ("fill", selector, text) = typing (not a click)."""
        clicks = [s for s in steps if isinstance(s, str)]
        if len(clicks) > 3:
            problems.append(f"S1 {name}: {len(clicks)} clicks")
        page.goto(f"{base}/products")
        try:
            for step in steps:
                if isinstance(step, str):
                    page.locator(step).first.click()
                    page.wait_for_load_state()
                else:
                    page.locator(step[1]).first.fill(step[2])
            if not done():
                problems.append(f"S1 {name}: no result after {len(clicks)} clicks ({page.url})")
        except Exception as exc:  # a missing button = the job takes more clicks
            problems.append(f"S1 {name}: {str(exc).splitlines()[0]}")

    flow("change a price", [f"{row} a.name", ("fill", "#pane-prices input[name=price_5]", "19,000"),
                            "#pane-prices button.primary"],
         lambda: value(f"SELECT price_mmk FROM product_prices WHERE product_id = {stw} AND size_ml = 5 "
                       "ORDER BY effective_from DESC, id DESC LIMIT 1") == 19000)
    bottles = value(f"SELECT count(*) FROM bottles WHERE product_id = {stw}")
    flow("add a received bottle", [f"{row} a.stock-link", "#pane-stock summary:has-text('Add bottle')",
                                   ("fill", "#pane-stock details[open] input[name=cost_mmk]", "250000"),
                                   "#pane-stock details[open] button.primary"],
         lambda: value(f"SELECT count(*) FROM bottles WHERE product_id = {stw}") == bottles + 1)
    flow("fix the ml", [f"{row} a.stock-link", "#pane-stock summary:has-text('Fix the amount')",
                        ("fill", "#pane-stock details[open] input[name=remaining_ml]", "42"),
                        ("fill", "#pane-stock details[open] input[name=reason]", "count"),
                        "#pane-stock details[open] button.primary"],
         lambda: value(f"SELECT count(*) FROM bottles WHERE product_id = {stw} AND remaining_ml = 42") == 1)
    flow("add a nickname", [f"{row} .col-num a", ("fill", "#pane-nicks input[name=alias]", "swy int"),
                            "#pane-nicks form.inline-form button.primary"],
         lambda: value(f"SELECT count(*) FROM product_aliases WHERE product_id = {stw} AND normalized_alias = 'swy int'") == 1)
    flow("see what to reorder", [".warn-bar a:has-text('Show only these')"],
         lambda: page.locator("#product-list .list-row").count() >= 1
         and page.locator("#product-list a.name:text-is('Sauvage Eau de Parfum')").count() == 1
         and page.locator(f"{row}").count() == 0)
    flow("add a perfume", [".head-actions a.button.primary", ("fill", ".dialog input[name=brand]", "Creed"),
                           ("fill", ".dialog input[name=name]", "Aventus"), ("fill", ".dialog input[name=price_5]", "65,000"),
                           ".dialog button.primary"],
         lambda: value("SELECT count(*) FROM products WHERE name = 'Aventus'") == 1)
    page.goto(f"{base}/products?open={stw}")
    page.locator("body").click(position={"x": 400, "y": 5})
    page.keyboard.press("Escape")
    try:
        page.wait_for_selector("#panel.side-panel", state="detached", timeout=3000)
    except Exception:
        problems.append("S1 Esc does not close the panel")
    context.close()

    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    log_in(page, "staff1")
    set_language(page, "en")
    page.goto(f"{base}/products?open={stw}")
    if (page.locator(".head-actions").count() or page.locator("#panel button").count()
            or page.locator("#pane-prices input[readonly]").count() < 4):
        problems.append("S1 staff: the Products page is not view-only")
    context.close()
    db.dispose()
    return problems


def chat_flows(browser) -> list[str]:
    """docs/SPEC-v5.7 D2-D4 on a PC (1440 px): the 600-message chat opens with 20 bubbles; scrolling up 3 times loads
    20 more each time without moving the bubble being read, no double; a new message appears at the bottom by
    itself, and while scrolled up it shows "New message ↓" instead of jumping; typed text stays (the thread is not
    re-drawn); a reply can be sent and cancelled; a link to an old message (#m...) loads until it is there."""
    from sqlalchemy import create_engine, text

    problems, base = [], f"http://127.0.0.1:{PORT}"
    db = create_engine(get_settings().database_url)
    with db.connect() as c:
        cid = c.execute(text("SELECT id FROM customers WHERE external_user_id = 'ui-long'")).scalar()
        old = c.execute(text("SELECT id FROM messages WHERE customer_id = :c ORDER BY received_at, id OFFSET 30 LIMIT 1"),
                        {"c": cid}).scalar()
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    log_in(page, "owner")
    set_language(page, "en")

    def check(name: str, ok) -> None:
        try:
            if not ok():
                problems.append(f"CHAT {name}: failed")
        except Exception as exc:
            problems.append(f"CHAT {name}: {str(exc).splitlines()[0]}")

    def count() -> int:
        return page.locator("#thread .bubble:not(.pending)").count()

    def say(n: int, words: str) -> None:
        with db.begin() as c:
            c.execute(text("INSERT INTO messages (channel, external_chat_id, external_message_id, customer_id, raw_text, "
                           "normalized_text, received_at, direction, kind) VALUES ('telegram', 'ui-long', :e, :c, :w, :w, "
                           "now(), 'in', 'text')"), {"e": f"ui-long-new-{n}", "c": cid, "w": words})

    page.goto(f"{base}/chats/{cid}")
    page.wait_for_selector("#thread .bubble")
    check("opens with 20 bubbles", lambda: count() == 20)
    page.wait_for_timeout(600)  # the top watcher starts after the chat has opened at the bottom
    for n in range(3):
        before = count()
        top = page.evaluate("""() => { const p = document.querySelector('.chat-pane'), b = document.querySelector('#thread .bubble');
            p.scrollTop = 0; window.readId = b.id; return b.getBoundingClientRect().top; }""")
        for _ in range(50):  # (no wait_for_function: it needs eval, which our CSP blocks)
            if count() >= before + 20:
                break
            page.wait_for_timeout(100)
        else:
            problems.append(f"CHAT scroll up {n + 1}: no older messages")
            break
        page.wait_for_timeout(100)
        moved = page.evaluate("() => document.getElementById(window.readId).getBoundingClientRect().top") - top
        if abs(moved) > 3:
            problems.append(f"CHAT scroll up {n + 1}: the bubble being read moved {moved:.0f}px")
    ids = page.evaluate("() => [...document.querySelectorAll('#thread .bubble[id]')].map(b => b.id)")
    check("no double bubbles after scrolling up", lambda: len(ids) == len(set(ids)) == 80)
    check("one separator per day", lambda: page.evaluate("""() => { const d = [...document.querySelectorAll('#thread .day-sep')]
        .map(s => s.dataset.day); return d.length === new Set(d).size; }"""))

    page.evaluate("() => { const p = document.querySelector('.chat-pane'); p.scrollTop = p.scrollHeight; document.getElementById('thread').dataset.mark = '1'; }")
    say(1, "new at the bottom")
    check("new message appears at the bottom", lambda: page.locator("#thread .bubble", has_text="new at the bottom")
          .wait_for(timeout=7000) is None and page.evaluate(
              "() => { const p = document.querySelector('.chat-pane'); return p.scrollHeight - p.scrollTop - p.clientHeight < 80; }"))
    page.fill("form.compose-box textarea[name=text]", "half a reply")
    up = page.evaluate("() => { const p = document.querySelector('.chat-pane'); p.scrollTop = p.scrollHeight - p.clientHeight - 600; return p.scrollTop; }")
    say(2, "new while scrolled up")
    check("scrolled up: pill, no jump", lambda: page.locator("#new-pill:not([hidden])").wait_for(timeout=7000) is None
          and abs(page.evaluate("() => document.querySelector('.chat-pane').scrollTop") - up) < 3)
    if page.locator("#new-pill").is_visible():
        page.locator("#new-pill").click()
    check("pill goes to the new message", lambda: page.locator("#thread .bubble", has_text="new while scrolled up").is_visible())
    page.wait_for_timeout(8500)  # two poll rounds
    check("typed text stays, thread not re-drawn", lambda: page.input_value("form.compose-box textarea[name=text]")
          == "half a reply" and page.evaluate("() => document.getElementById('thread').dataset.mark") == "1")

    page.fill("form.compose-box textarea[name=text]", "reply to cancel")
    page.locator("form.compose-box button.send-round").click()
    check("send shows the reply", lambda: page.locator("#pending .bubble", has_text="reply to cancel").wait_for() is None)
    cancel = page.locator("#pending .bubble", has_text="reply to cancel").locator("button", has_text="Cancel")
    if cancel.count():
        cancel.click()
        page.wait_for_load_state()
        with db.connect() as c:
            check("cancel within the undo window", lambda: c.execute(text(
                "SELECT status FROM outbox WHERE text = 'reply to cancel'")).scalar() == "cancelled")
    else:
        problems.append("CHAT the sent reply has no Cancel button")

    page.goto(f"{base}/help")  # a link from another page (the same page with a new #hash would not reload)
    page.goto(f"{base}/chats/{cid}#m{old}")
    check("#m link to an old message loads it", lambda: page.locator(f"#m{old}").wait_for(timeout=15000) is None)
    context.close()
    db.dispose()
    return problems


def c8(browser, targets) -> list[str]:
    """C8 at 1440 / 1920 / 2560 px, English, owner + staff, every full page and the login page."""
    problems, shots = [], SHOTS / "5.5"
    shots.mkdir(parents=True, exist_ok=True)
    for role, username in (("owner", "owner"), ("staff", "staff1")):
        context = browser.new_context()
        page = context.new_page()
        if role == "owner":
            for width in C8_WIDTHS:
                page.set_viewport_size({"width": width, "height": 1000})
                page.goto(f"http://127.0.0.1:{PORT}/login")
                page.screenshot(path=shots / f"login-{width}.png")
                problems += [f"login {width}: {p}" for p in page.evaluate(C8_JS)]
        log_in(page, username)
        set_language(page, "en")
        for width in C8_WIDTHS:
            page.set_viewport_size({"width": width, "height": 1000})
            for name, url, partial in targets:
                if partial or page.goto(f"http://127.0.0.1:{PORT}{url}").status != 200:
                    continue  # staff 403 pages are C1/C7's job
                if role == "owner" and name in C8_SHOTS:
                    page.screenshot(path=shots / f"{name}-{width}.png", full_page=True)
                problems += [f"{name} {role} {width}: {p}" for p in page.evaluate(C8_JS)]
        context.close()
    return problems


def run(quick: bool, save_inventory: bool, only_widths: tuple[int, ...] = (), shots: Path | None = None,
        only_pages: tuple[str, ...] = ()) -> int:
    from playwright.sync_api import sync_playwright

    global SHOTS
    SHOTS = shots or SHOTS

    use_check_database()
    ids = build_database()
    serve()
    SHOTS.mkdir(parents=True, exist_ok=True)
    targets = pages(ids)
    if quick:
        targets = [t for t in targets if t[0] in DAILY]
    if only_pages:
        targets = [t for t in targets if t[0] in only_pages]
    widths, langs = ((360,), ("my", "en")) if quick else (WIDTHS, ("en", "my"))
    widths = only_widths or widths  # e.g. --widths 1440,390 for screenshots next to the mockups (docs/SPEC-v5.4 U0)
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
        if not quick and not save_inventory:
            for problem in c8(browser, targets):
                failures += 1
                lines.append("FAIL C8 " + problem)
        if not save_inventory and not only_pages:  # the flows need every page
            for problem in pc_flows(browser) + chat_flows(browser) + u4_flows(browser) + s1_flows(browser):
                failures += 1
                lines.append("FAIL " + problem)
        elif not save_inventory and ("products" in only_pages or "chat-long" in only_pages):  # quick looks click too
            for problem in (s1_flows(browser) if "products" in only_pages else []) + (
                    chat_flows(browser) if "chat-long" in only_pages else []):
                failures += 1
                lines.append("FAIL " + problem)
        browser.close()

    if save_inventory:  # "_..." keys are notes (docs/SPEC-v5.6 S3: where moved controls went); they stay
        notes = {k: v for k, v in json.loads(INVENTORY.read_text()).items() if k.startswith("_")} if INVENTORY.exists() else {}
        INVENTORY.write_text(json.dumps(notes | inventory, indent=1, ensure_ascii=False) + "\n")
        print(f"saved {INVENTORY.relative_to(ROOT)} ({len(inventory)} pages)")
    elif INVENTORY.exists() and not (only_pages or only_widths):  # C7 (needs the full run): nothing that existed before is gone (same role)
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
    parser.add_argument("--widths", default="", help="comma list, e.g. 1440,390 (default 360,768,1280)")
    parser.add_argument("--shots", type=Path, help="screenshot folder (default ui-shots/)")
    parser.add_argument("--pages", default="", help="comma list of page names, e.g. products,ai (quick look)")
    args = parser.parse_args()
    sys.exit(run(args.quick, args.save_inventory, tuple(int(w) for w in args.widths.split(",") if w), args.shots,
                 tuple(p for p in args.pages.split(",") if p)))
