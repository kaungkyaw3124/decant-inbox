"""docs/SPEC-v5.9-reliability-under-load.md T1-T9: chaos / stress tests. Scratch database, FAKE Telegram client;
nothing reaches a real customer; the send limits are the real ones (on a virtual clock, see harness.SPEED)."""
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import BASE_DIR, get_settings
from app.core.db import SessionLocal
from app.listener import sender
from app.orders import holding
from tests.chaos.harness import (
    FIRST_USER, REPLY_WITHIN, assert_invariants, median, percentile, rows, run_flows, scalar, wait_until,
)


# ---------- T1 / T2: the burst ----------

def test_t1_t2_burst_of_50_customers(chaos):
    since = datetime.now(UTC)
    uids = chaos.customers(50)
    chaos.listener.start()
    chaos.start_worker()
    result = run_flows(chaos, uids)
    if os.environ.get("CHAOS_DEBUG"):
        with open(os.environ["CHAOS_DEBUG"] + ".flow", "w") as f:
            for u in uids[:3]:
                print(u, result[u], file=f)
                print([(m.out, m.message[:25], m.date.strftime("%H:%M:%S.%f")[:-3]) for m in chaos.fake.history[u]], file=f)
            print(rows("SELECT m.customer_id, m.raw_text, m.received_at, r.status, r.reason, r.created_at, "
                       "(SELECT count(*) FROM audit_log a WHERE a.action = 'auto.holding' AND "
                       "(a.details->>'message_id')::int = m.id) FROM messages m LEFT JOIN auto_runs r ON r.message_id = m.id "
                       "WHERE m.direction = 'in' AND m.customer_id <= 3 ORDER BY m.id"), file=f)
    paid = wait_until(lambda: scalar("SELECT count(*) FROM orders WHERE order_no IS NOT NULL") >= 50, 60)
    if not paid and os.environ.get("CHAOS_DEBUG"):
        with open(os.environ["CHAOS_DEBUG"], "w") as f:
            print(rows("SELECT action, details FROM audit_log WHERE action LIKE 'test_code%'"), file=f)
            for u in uids[:50]:
                print(u, [(m.out, m.message[:30], m.date.isoformat()) for m in chaos.fake.history[u]], file=f)
            print(rows("SELECT m.id, m.customer_id, m.raw_text, m.received_at, r.status, r.reason FROM messages m "
                       "LEFT JOIN auto_runs r ON r.message_id = m.id WHERE m.direction = 'in' ORDER BY m.id"), file=f)
    assert paid, rows("SELECT customer_id, status FROM orders WHERE order_no IS NULL")
    assert wait_until(lambda: not scalar("SELECT count(*) FROM outbox WHERE status IN ('queued', 'sending')"), 60)
    missing = {uid: r["missing"] for uid, r in result.items() if r["missing"]}
    assert not missing, f"no reply / Needs-you item within {REPLY_WITHIN} s: {missing}"
    # 0 lost: every message the fake account received is saved
    received = sum(1 for uid in uids for m in chaos.fake.history[uid] if not m.out)
    assert scalar("SELECT count(*) FROM messages WHERE direction = 'in' AND received_at >= :s", s=since) == received
    # order numbers unique, one paid (test) order each, stock deducted at most once per order
    numbers = [r[0] for r in rows("SELECT order_no FROM orders WHERE is_test AND order_no IS NOT NULL")]
    assert len(numbers) == 50 and len(set(numbers)) == 50
    assert not rows("SELECT order_id FROM stock_moves WHERE order_id IS NOT NULL AND kind = 'decant' "
                    "GROUP BY order_id, product_id, vial_size HAVING count(*) > 1")
    # the real limits (virtual clock): at most 20 sends per minute
    assert chaos.fake.max_per_minute() <= sender.MAX_PER_MINUTE
    # fairness: nobody waits more than 2x the median for the whole flow
    lasts = [r["last"] for r in result.values()]
    assert max(lasts) <= 2 * median(lasts), sorted(lasts)
    # T2: the capacity numbers (REPORT.md "5.9 scoreboard")
    firsts = [r["first"] for r in result.values() if r["first"] is not None]
    numbers = {"customers": len(uids), "sends": len(chaos.fake.sent),
               "needs_you_first": sum(r["needs_you"] for r in result.values()),
               "first_reply_s": {"p50": median(firsts), "p90": percentile(firsts, 90), "max": max(firsts)},
               "last_reply_s": {"p50": median(lasts), "p90": percentile(lasts, 90), "max": max(lasts)},
               "max_sends_per_virtual_minute": chaos.fake.max_per_minute()}
    print("T2", json.dumps(numbers))
    out = BASE_DIR / "data" / "exports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "chaos_t2.json").write_text(json.dumps(numbers, indent=1))
    assert_invariants(chaos.fake, since)


# ---------- T3: crash while sending ----------

@pytest.mark.parametrize("where", ["before", "after"])
def test_t3_crash_while_sending_sends_exactly_once(chaos, where):
    since = datetime.now(UTC)
    (uid,) = chaos.customers(1)
    chaos.listener.start()
    chaos.start_worker()
    chaos.fake.crash = where  # the next send kills the listener (between claim and send / send and mark_sent)
    chaos.listener.run(chaos.fake.incoming(uid, "stw intensely 5ml ဘယ်လောက်လဲ"))
    assert wait_until(lambda: not chaos.listener.alive(), 20), "the listener should have crashed"
    assert scalar("SELECT count(*) FROM outbox WHERE status = 'sending'") >= 1
    chaos.listener.stop()
    chaos.listener.start()  # systemd restarts it
    assert wait_until(lambda: not scalar("SELECT count(*) FROM outbox WHERE status IN ('queued', 'sending')"), 30), \
        rows("SELECT id, status, error FROM outbox")
    sent = rows("SELECT id, text FROM outbox WHERE status = 'sent'")
    assert sent
    for _, body in sent:  # each reply exactly once in the fake's sent history
        assert chaos.fake.sent_to(uid).count(body.strip()) == 1, (body, chaos.fake.sent_to(uid))
    assert scalar("SELECT count(*) FROM outbox WHERE status = 'failed'") == 0
    assert_invariants(chaos.fake, since)


# ---------- T4: transient errors ----------

def test_t4_transient_errors_retry_then_fail_with_alert(chaos):
    from app.alerts import service as alerts

    since = datetime.now(UTC)
    uids = chaos.customers(6)
    bad = uids[-1]

    def fail(uid, n):
        if uid == bad:
            return TimeoutError("timed out")  # every try to this customer
        return TimeoutError("timed out") if n % 5 == 0 else None  # every 5th send

    chaos.fake.fail = fail
    chaos.listener.start()
    chaos.start_worker()
    result = run_flows(chaos, uids[:-1], steps=3)
    assert not {u: r["missing"] for u, r in result.items() if r["missing"]}
    assert wait_until(lambda: not scalar("SELECT count(*) FROM outbox o JOIN customers c ON c.id = o.customer_id "
                                         "WHERE c.external_user_id <> :b AND o.status <> 'sent'", b=str(bad)), 30)
    # the customer we cannot reach: the reply fails after the retries, Needs you + alert, then silence
    chaos.listener.run(chaos.fake.incoming(bad, "stw intensely 5ml ဘယ်လောက်လဲ"))
    assert wait_until(lambda: scalar("SELECT count(*) FROM outbox o JOIN customers c ON c.id = o.customer_id "
                                     "WHERE c.external_user_id = :b AND o.status = 'failed'", b=str(bad)), 40), \
        rows("SELECT status, attempts, error FROM outbox")
    assert scalar("SELECT max(attempts) FROM outbox WHERE status = 'failed'") == 1 + len(sender.RETRY_DELAYS)
    from app.web.auto import for_customer, needs_you

    cid = scalar("SELECT id FROM customers WHERE external_user_id = :b", b=str(bad))
    with SessionLocal() as s:
        assert for_customer(needs_you(s), cid)["failed"], "a failed reply is a Needs-you item"
    got = []
    alerts.tick(send=lambda body, button=None: got.append(body))
    assert any("Reply to" in g and "failed" in g for g in got), got
    boxes = scalar("SELECT count(*) FROM outbox WHERE customer_id = :c", c=cid)
    time.sleep(holding.WAIT.total_seconds() + 3)  # the silence watchdog sends nothing more to this customer
    assert scalar("SELECT count(*) FROM outbox WHERE customer_id = :c", c=cid) == boxes
    assert chaos.fake.sent_to(bad) == []
    assert_invariants(chaos.fake, since)


# ---------- T5: database down ----------

def test_t5_database_down_20s_nothing_lost(chaos):
    since = datetime.now(UTC)
    uids = chaos.customers(10)
    chaos.listener.start()
    chaos.start_worker()
    real_save = chaos.main._save
    down = threading.Event()

    def save(msg):
        if down.is_set():
            raise OperationalError("INSERT", {}, Exception("connection refused"))
        return real_save(msg)

    chaos.monkeypatch.setattr(chaos.main, "_save", save)
    down.set()
    started = time.monotonic()

    async def twenty():
        for i in range(20):
            await chaos.fake.incoming(uids[i % 10], f"stw intensely {5 if i < 10 else 10}ml ဘယ်လောက်လဲ")
            await asyncio.sleep(0.5)

    chaos.listener.run(twenty())
    time.sleep(max(0.0, 20 - (time.monotonic() - started)))
    down.clear()  # the database is back
    assert wait_until(lambda: scalar("SELECT count(*) FROM messages WHERE direction = 'in' AND received_at >= :s",
                                     s=since) == 20, 30)
    assert chaos.listener.alive(), "no crash loop"
    assert wait_until(lambda: not rows(
        "SELECT m.id FROM messages m WHERE m.direction = 'in' AND m.received_at >= :s AND NOT EXISTS ("
        "SELECT 1 FROM outbox o WHERE o.customer_id = m.customer_id AND o.created_at >= m.created_at)", s=since), 40)
    assert_invariants(chaos.fake, since)


# ---------- T6: missed messages while the listener was stopped ----------

def test_t6_messages_missed_while_stopped_are_saved(chaos):
    since = datetime.now(UTC)
    uids = chaos.customers(10)
    chaos.start_worker()

    async def forty():
        for i in range(40):
            await chaos.fake.incoming(uids[i % 10], f"stw intensely {i % 3 * 5 + 5}ml ရှိလား")

    chaos.listener.run(forty())  # the listener is not running: Telegram holds them
    assert scalar("SELECT count(*) FROM messages WHERE received_at >= :s", s=since) == 0
    chaos.listener.start()
    assert wait_until(lambda: scalar("SELECT count(*) FROM messages WHERE direction = 'in' AND received_at >= :s",
                                     s=since) == 40, 2 * chaos.listener.gap_every + 5)
    assert wait_until(lambda: not scalar("SELECT count(*) FROM outbox WHERE status IN ('queued', 'sending')")
                      and scalar("SELECT count(DISTINCT customer_id) FROM outbox WHERE status = 'sent'") == 10, 60)
    assert_invariants(chaos.fake, since)


# ---------- T7: big history + catalog change while customers write ----------

def test_t7_reparse_never_freezes_live_replies(chaos):
    since = datetime.now(UTC)
    uids = chaos.customers(20)
    with SessionLocal.begin() as s:  # 5,000 old messages of 500 other customers over 30 days; 1,000 not parsed yet
        s.execute(text(
            "INSERT INTO customers (channel, external_user_id, display_name) "
            "SELECT 'telegram', (800000 + g)::text, 'Old ' || g FROM generate_series(1, 500) g"))
        s.execute(text(
            "INSERT INTO messages (channel, external_chat_id, external_message_id, customer_id, raw_text, "
            "normalized_text, received_at, direction, kind) "
            "SELECT 'telegram', c.external_user_id, 'old-' || g, c.id, "
            "(ARRAY['stw intensely 5ml ရှိလား', 'sauvage edp 10ml ဘယ်လောက်လဲ', 'aventus 10ml ယူမယ်', 'ok ပါ'])[1 + g % 4], "
            "(ARRAY['stw intensely 5ml ရှိလား', 'sauvage edp 10ml ဘယ်လောက်လဲ', 'aventus 10ml ယူမယ်', 'ok ပါ'])[1 + g % 4], "
            "now() - (g % 30 + 1) * interval '1 day', 'in', 'text' "
            "FROM generate_series(1, 5000) g JOIN customers c ON c.external_user_id = (800000 + 1 + g % 500)::text"))
        s.execute(text(
            "INSERT INTO parse_results (message_id, intent, quantity, confidence, method, parser_version, is_current) "
            "SELECT id, 'other', 1, 0.5, 'rules', 'old', true FROM messages WHERE external_message_id LIKE 'old-%' "
            "ORDER BY id LIMIT 4000"))
    chaos.listener.start()
    w = chaos.start_worker()
    assert wait_until(lambda: scalar("SELECT count(*) FROM service_heartbeats WHERE name = 'parser'"), 60)
    with SessionLocal.begin() as s:  # an alias edited in the dashboard -> the worker re-parses
        s.execute(text("INSERT INTO product_aliases (product_id, alias_text, normalized_alias, source) "
                       "SELECT id, 'chaos nick', 'chaos nick', 'seed' FROM products ORDER BY id LIMIT 1"))
    worst_beat = [0.0]
    stop = threading.Event()

    def watch_heartbeat():
        while not stop.is_set():
            age = scalar("SELECT extract(epoch FROM now() - last_seen) FROM service_heartbeats WHERE name = 'parser'")
            worst_beat[0] = max(worst_beat[0], float(age or 0))
            time.sleep(1)

    watcher = threading.Thread(target=watch_heartbeat, daemon=True)
    watcher.start()
    time.sleep(1)
    waits = {}

    async def customer(uid):
        await chaos.fake.incoming(uid, "stw intensely 10ml ဘယ်လောက်လဲ")
        asked = time.monotonic()
        while not chaos.fake.sent_to(uid) and time.monotonic() - asked < 60:
            await asyncio.sleep(0.05)
        waits[uid] = time.monotonic() - asked

    async def everyone():
        for uid in uids:  # 20 new messages over ~10 s while the re-parse runs
            asyncio.ensure_future(customer(uid))
            await asyncio.sleep(0.5)
        while len(waits) < len(uids):
            await asyncio.sleep(0.1)

    chaos.listener.run(everyone())
    stop.set()
    watcher.join(5)
    assert max(waits.values()) <= 5.0, sorted(round(v, 1) for v in waits.values())
    assert worst_beat[0] <= 60, worst_beat
    assert w.error is None
    assert_invariants(chaos.fake, since)


# ---------- T8: dashboard tabs + pages during a burst ----------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Browser:
    """One logged-in user over plain http (the session cookie is Secure, so it is carried by hand)."""

    def __init__(self, base: str, username: str, password: str):
        self.http = httpx.Client(base_url=base, timeout=30, follow_redirects=False)
        self.cookie = ""
        page = self.get("/login")
        token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        r = self.post("/login", {"username": username, "password": password, "csrf": token, "next": "/"})
        assert r.status_code == 303 and r.headers["location"] == "/", (r.status_code, r.headers.get("location"))

    def _keep(self, r):
        for header in r.headers.get_list("set-cookie"):
            if header.startswith("decant_session="):
                self.cookie = header.split(";", 1)[0]
        return r

    def get(self, path: str):
        return self._keep(self.http.get(path, headers={"Cookie": self.cookie}))

    def post(self, path: str, data: dict):
        return self._keep(self.http.post(path, data=data, headers={"Cookie": self.cookie}))


def test_t8_tabs_and_pages_during_burst(chaos, tmp_path):
    from app.web.auth import hash_password
    from app.models import User

    since = datetime.now(UTC)
    with SessionLocal.begin() as s:
        for i in range(20):
            s.add(User(username=f"tab{i}", password_hash=hash_password("chaos-pass-1"), role="owner"))
    port = _free_port()
    log = (tmp_path / "web.log").open("w")
    env = {**os.environ, "DB_POOL_SIZE": "20", "DB_MAX_OVERFLOW": "20", "WEB_COOKIE_SECURE": "false"}
    web = subprocess.Popen(  # the web service as systemd runs it (own process, deploy/systemd/decant-web.service)
        [sys.executable, "-m", "uvicorn", "app.web.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--no-access-log"], cwd=BASE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{port}"
        assert wait_until(lambda: _up(base), 60), (tmp_path / "web.log").read_text()[-2000:]
        browsers = [Browser(base, f"tab{i}", "chaos-pass-1") for i in range(20)]
        uids = chaos.customers(50)
        chaos.listener.start()
        chaos.start_worker()
        before = scalar("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
        stop, streams_ok, worst_conn = threading.Event(), [], [0]

        def stream(b: Browser):
            with b.http.stream("GET", "/events", headers={"Cookie": b.cookie}, timeout=30) as r:
                streams_ok.append(r.status_code == 200)
                for _ in r.iter_lines():
                    if stop.is_set():
                        break

        def connections():
            while not stop.is_set():
                worst_conn[0] = max(worst_conn[0], scalar(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"))
                time.sleep(0.2)

        threads = [threading.Thread(target=stream, args=(b,), daemon=True) for b in browsers]
        threads.append(threading.Thread(target=connections, daemon=True))
        for t in threads:
            t.start()
        burst = threading.Thread(target=run_flows, args=(chaos, uids, 2), daemon=True)
        burst.start()
        time.sleep(2)
        times, codes = [], []
        pages = ["/", "/orders", "/customers", "/health", "/sales", "/chats"]

        def page(i: int):
            started = time.monotonic()
            codes.append(browsers[i % 20].get(pages[i % len(pages)]).status_code)
            times.append(time.monotonic() - started)

        loaders = [threading.Thread(target=page, args=(i,)) for i in range(30)]
        for t in loaders:  # 30 page requests at once
            t.start()
        for t in loaders:
            t.join(60)
        burst.join(180)
        stop.set()
        for b in browsers:
            b.http.close()
        assert all(c == 200 for c in codes), (codes, browsers[0].get("/").headers.get("location"), browsers[0].cookie[:20])
        assert len(streams_ok) == 20 and all(streams_ok)
        assert percentile(times, 90) <= 1.0, sorted(round(t, 2) for t in times)
        logs = (tmp_path / "web.log").read_text()
        assert "QueuePool limit" not in logs and "database pool full" not in logs, logs[-2000:]
        # the web process stays within its pool (20 + 20) plus ONE listening connection for all tabs
        assert worst_conn[0] - before <= 20 + 20 + 1, (before, worst_conn[0])
        assert worst_conn[0] - before <= 20, f"20 tabs should not need 20 extra connections ({before} -> {worst_conn})"
    finally:
        web.terminate()
        try:
            web.wait(15)
        except subprocess.TimeoutExpired:  # open live streams keep a graceful shutdown waiting
            web.kill()
            web.wait(10)
        log.close()
    assert_invariants(chaos.fake, since)


def _up(base: str) -> bool:
    try:
        return httpx.get(base + "/healthz", timeout=2).status_code in (200, 503)
    except httpx.HTTPError:
        return False


# ---------- T9: double click on Approve ----------

def test_t9_approve_from_10_threads_once(chaos):
    from app.models import PaymentCheck, User
    from app.orders import payments
    from app.replies import templates as replies
    from scripts.simulate import Chat

    since = datetime.now(UTC)
    chat = Chat(FIRST_USER - 600000)  # simulate.Chat ids are FIRST_ID + n
    chat.setup({"state": "photo_received", "items": ["Stronger With You Intensely 5ml"]})
    with SessionLocal.begin() as s:
        check = s.scalar(text("SELECT id FROM payment_checks"))
        s.get(PaymentCheck, check).is_test = True  # no screenshot to open: the test path of approve()
        user_id = s.scalar(text("SELECT id FROM users"))
    results, gate = [], threading.Barrier(10)

    def click():
        with SessionLocal() as db:
            row = db.get(PaymentCheck, check)
            gate.wait()
            try:
                found = payments.approve(db, row, payments.Form("", None, None), db.get(User, user_id),
                                         replies.load(db), True)
                db.commit()
                results.append("ok" if not found else "warn")
            except payments.PaymentError:
                db.rollback()
                results.append("refused")
            except Exception as exc:  # a lock / serialization error is a refusal too, never a second order
                db.rollback()
                results.append(type(exc).__name__)

    threads = [threading.Thread(target=click) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert results.count("ok") == 1, results
    assert scalar("SELECT count(*) FROM orders WHERE order_no IS NOT NULL") == 1
    assert scalar("SELECT count(*) FROM outbox WHERE reply_kind = 'payment'") == 1
    assert scalar("SELECT count(*) FROM audit_log WHERE action = 'payment.approve'") == 1
    assert not rows("SELECT 1 FROM stock_moves WHERE kind = 'decant' GROUP BY order_id, product_id, vial_size "
                    "HAVING count(*) > 1")
    chaos.listener.start()
    assert wait_until(lambda: scalar("SELECT count(*) FROM outbox WHERE status = 'sent'") == 1, 30)
    assert len(chaos.fake.sent_to(int(chat.user))) == 1  # one "paid" message
    assert_invariants(chaos.fake, since)
