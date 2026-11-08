"""docs/SPEC-v5.3-performance-pc.md M0: how fast the dashboard feels on a PC browser.

Runs on a COPY of the live database (<db>_replay, made by scripts/replay_live.copy_live, deleted after), with a
throw-away owner login that exists only in the copy, a local web server, AI off and no listener (nothing can
reach Telegram: a reply "sent" in the copy only becomes an outbox row there). Chromium at 1440x900 with the
network slowed like the Cloudflare tunnel from Myanmar: 150 ms round trip, 5 Mbit/s.

Measures: each main page cold (first visit after login, empty browser cache) and warm (second visit), 10
customer switches in Chats, one reply sent in the test chat; server time per route (Server-Timing).
Prints numbers only (never customer text).
Usage: nice -n 19 ionice -c3 .venv/bin/python -m scripts.perf_check [--keep]
"""
import os
import secrets
import sys

if __name__ == "__main__":  # point at the copy before app.core.db creates the engine
    from app.core.config import get_settings as _gs

    LIVE_DB = _gs().db_name
    os.environ.update(DB_NAME=LIVE_DB + "_replay", WEB_SECRET_KEY=secrets.token_urlsafe(32), AI_PROVIDER="off",
                      WEB_COOKIE_SECURE="false", ALERT_BOT_TOKEN="", ALERT_CHAT_ID="")
    _gs.cache_clear()

import argparse
import threading
import time

PORT = 8766
BASE = f"http://127.0.0.1:{PORT}"
PAGES = ("/chats", "/orders", "/payments", "/products", "/sales", "/settings")
RTT_MS, MBIT = 150, 5
USER = "perf-check"
SETTLED = """() => document.readyState === 'complete' && !document.querySelector('.htmx-request')
                && document.fonts.status === 'loaded'"""


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))] if ordered else float("nan")


class Net:
    """Bytes on the wire and requests per step, from Chrome itself (cached files count 0 bytes)."""

    def __init__(self, page):
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.send("Network.enable")
        self.cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": RTT_MS, "downloadThroughput": MBIT * 125_000,
            "uploadThroughput": MBIT * 125_000})
        self.bytes = self.requests = 0
        self.cdp.on("Network.requestWillBeSent", lambda e: setattr(self, "requests", self.requests + 1))
        self.cdp.on("Network.loadingFinished", lambda e: setattr(self, "bytes", self.bytes + e["encodedDataLength"]))

    def reset(self) -> None:
        self.bytes = self.requests = 0


LONG_CHAT = 600


def seed_long_chat(session, external: str = "perf-long", end=None) -> int:
    """docs/SPEC-v5.7 D2: a fake customer with 600 messages (every 25th a photo, some albums), never a real chat:
    only in a throw-away database (the perf copy, the ui_check database)."""
    from datetime import UTC, datetime, timedelta

    from app.models import Customer, Message

    customer = Customer(channel="telegram", external_user_id=external, display_name="Long chat (test)")
    session.add(customer)
    session.flush()
    start = (end or datetime.now(UTC) - timedelta(hours=1)) - timedelta(minutes=97 * LONG_CHAT)  # default: last one an hour ago
    for n in range(LONG_CHAT):
        photo = n % 25 == 0
        session.add(Message(
            channel="telegram", external_chat_id=external, external_message_id=f"{external}-{n}",
            customer_id=customer.id, raw_text="" if photo else f"message {n} " + "word " * (n % 7),
            normalized_text=None, received_at=start + timedelta(minutes=97 * n),
            direction="out" if n % 3 == 2 else "in", kind="photo" if photo else "text",
            grouped_id=f"album-{n // 50}" if photo and n % 50 == 0 else None, media_size=120_000 if photo else None))
    session.flush()
    return customer.id


def long_chat(page, net, customer_id: int) -> list[dict]:
    """Open the 600-message chat 5 times (warm): seconds, KB, bubbles in the page, server ms (Server-Timing)."""
    out = []
    for _ in range(5):
        r = timed(page, net, lambda: page.goto(f"{BASE}/chats/{customer_id}"), f"/chats/{customer_id}")
        api = page.request.get(f"{BASE}/chats/{customer_id}")
        r["server_ms"] = float(api.headers["server-timing"].rsplit("total;dur=", 1)[1])
        r["bubbles"] = page.locator("#thread .bubble").count()
        out.append(r)
    return out


def timed(page, net, action, url_part: str) -> dict:
    net.reset()
    started = time.perf_counter()
    action()
    page.wait_for_url(f"**{url_part}*", wait_until="commit")
    page.wait_for_function(SETTLED)
    return {"s": time.perf_counter() - started, "kb": net.bytes / 1024, "requests": net.requests}


def click_menu(page, href: str):
    link = page.locator(f"nav.sidebar a[href='{href}'], nav.sidebar .more-list a[href='{href}']").first
    if not link.is_visible():
        page.locator("nav.sidebar details.more-menu summary").click()
    link.click()


def run(browser, test_customer: int, long_customer: int) -> dict:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    net = Net(page)
    from tests.test_web import PASSWORD

    out = {"cold": {}, "warm": {}, "switch": [], "send": None}
    page.goto(f"{BASE}/login")
    page.fill("input[name=username]", USER)
    page.fill("input[name=password]", PASSWORD)
    out["login"] = timed(page, net, lambda: page.locator("form[action='/login'] button").first.click(), "/")
    for rnd in ("cold", "warm"):
        for href in PAGES:
            out[rnd][href] = timed(page, net, lambda h=href: click_menu(page, h), href)
    page.goto(f"{BASE}/chats")
    page.wait_for_function(SETTLED)
    rows = page.locator("ul.chatrows a.chatrow")
    hrefs = [rows.nth(i).get_attribute("href") for i in range(min(rows.count(), 10))]
    for href in hrefs:
        out["switch"].append(timed(page, net, lambda h=href: page.locator(f"a.chatrow[href='{h}']").click(), href))
    page.goto(f"{BASE}/chats/{test_customer}")
    page.wait_for_function(SETTLED)
    text = f"perf check {secrets.token_hex(3)}"
    page.fill("form.compose-box textarea[name=text]", text)
    net.reset()
    started = time.perf_counter()
    page.locator("form.compose-box button.send-round").click()
    page.locator("#thread", has_text=text).wait_for()
    out["send"] = time.perf_counter() - started
    out["long"] = long_chat(page, net, long_customer)
    context.close()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep the database copy")
    keep = parser.parse_args().keep
    from sqlalchemy import select, update

    from app.core.config import get_settings
    from app.core.db import SessionLocal
    from app.models import Customer, Message, User
    from app.web.auth import hash_password
    from scripts.replay_live import copy_live, drop_copy
    from scripts.ui_check import libs_env
    from tests.test_web import PASSWORD

    copy = get_settings().db_name
    print(f"copying the live database into {copy} ...", flush=True)
    copy_live(LIVE_DB, copy)
    try:
        with SessionLocal.begin() as s:
            s.add(User(username=USER, password_hash=hash_password(PASSWORD), role="owner"))
            s.execute(update(User).values(totp_secret=None).where(User.username == USER))
            test_customer = (s.scalar(select(Customer.id).where(Customer.is_tester).limit(1))
                             or s.scalar(select(Message.customer_id).where(Message.direction == "in")
                                         .order_by(Message.id.desc()).limit(1)))
            long_customer = seed_long_chat(s)
        import uvicorn
        from playwright.sync_api import sync_playwright

        from app.web import perf
        from app.web.main import app

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(env=libs_env())
            runs = [run(browser, test_customer, long_customer) for _ in range(3)]
            browser.close()
        report(runs, perf.summary())
    finally:
        if not keep:
            drop_copy(copy)


def report(runs: list[dict], server: list[dict]) -> None:
    print(f"\nnetwork profile: {RTT_MS} ms RTT, {MBIT} Mbit/s; 3 runs; seconds to usable (p50 / p90)")
    print(f"{'page':<12} {'cold p50':>9} {'cold p90':>9} {'KB':>7} {'req':>4} | {'warm p50':>9} {'warm p90':>9} "
          f"{'KB':>7} {'req':>4}")
    for href in PAGES:
        c, w = [r["cold"][href] for r in runs], [r["warm"][href] for r in runs]
        print(f"{href:<12} {pct([x['s'] for x in c], .5):9.2f} {pct([x['s'] for x in c], .9):9.2f} "
              f"{pct([x['kb'] for x in c], .5):7.0f} {pct([x['requests'] for x in c], .5):4.0f} | "
              f"{pct([x['s'] for x in w], .5):9.2f} {pct([x['s'] for x in w], .9):9.2f} "
              f"{pct([x['kb'] for x in w], .5):7.0f} {pct([x['requests'] for x in w], .5):4.0f}")
    first = [r["login"] for r in runs]
    print(f"first page after login (empty cache): p50 {pct([x['s'] for x in first], .5):.2f} s, "
          f"p90 {pct([x['s'] for x in first], .9):.2f} s, {pct([x['kb'] for x in first], .5):.0f} KB")
    sw = [x for r in runs for x in r["switch"]]
    print(f"customer switch: p50 {pct([x['s'] for x in sw], .5):.2f} s, p90 {pct([x['s'] for x in sw], .9):.2f} s, "
          f"{pct([x['kb'] for x in sw], .5):.0f} KB, {pct([x['requests'] for x in sw], .5):.0f} requests (n={len(sw)})")
    sends = [r["send"] for r in runs]
    print(f"send reply -> bubble shown: p50 {pct(sends, .5):.2f} s, p90 {pct(sends, .9):.2f} s")
    lc = [x for r in runs for x in r["long"]]
    print(f"open the {LONG_CHAT}-message chat: p50 {pct([x['s'] for x in lc], .5):.2f} s, "
          f"p90 {pct([x['s'] for x in lc], .9):.2f} s, {pct([x['kb'] for x in lc], .5):.0f} KB, "
          f"server p50 {pct([x['server_ms'] for x in lc], .5):.0f} ms / p90 {pct([x['server_ms'] for x in lc], .9):.0f} ms, "
          f"{pct([x['bubbles'] for x in lc], .5):.0f} bubbles (n={len(lc)})")
    print("\nserver time per route, ms (p50 / p90 / max, n):")
    for r in server:
        print(f"  {r['route']:<45} {r['p50']:7.0f} {r['p90']:7.0f} {r['max']:7.0f}  n={r['n']}")


if __name__ == "__main__":
    main()
