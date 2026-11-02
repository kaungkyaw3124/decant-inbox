"""docs/SPEC-v4.18-speed.md T1-T7: first reply within ~3 s (rules), AI in a pool, instant holding reply,
NOTIFY wake-ups with the poll as fallback, first replies before reminders, timings on /health."""
import asyncio
import time
from datetime import UTC, datetime, timedelta

import psycopg
from sqlalchemy import text

from app.ai import providers, service
from app.ai.providers import AIError
from app.core import notify
from app.core.db import SessionLocal
from app.listener import sender
from app.orders import auto, holding, speed
from app.parser import worker
from app.parser.worker import run_batch
from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_messaging import add, customer_id, scalar
from tests.test_v46_ai import ai, mode, ysl_answer  # noqa: F401  (fixture)
from tests.test_v4_teaching import auto_on
from tests.test_web import client, log_in  # noqa: F401  (fixture)

PRICE_Q = "stw intensely 5ml ဘယ်လောက်လဲ"


def mid(db, ext: int, customer: str) -> int:
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e AND customer_id = :c", e=str(ext),
                  c=customer_id(db, customer))


def boxes(db) -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text("SELECT customer_id, reply_kind, send_after, created_at FROM outbox ORDER BY id")))


def wait_for_pool(seconds: float = 10) -> None:
    end = time.monotonic() + seconds
    while worker._asking and time.monotonic() < end:
        time.sleep(0.05)
    assert not worker._asking, "AI pool still busy"


# ---------- T1 rules path ----------

def test_t1_rules_reply_due_within_3_s(shop, db):  # noqa: F811
    auto_on(db)
    assert auto.speed(SessionLocal()) == {"quiet_s": 0.7, "delay_min_s": 0.3, "delay_max_s": 0.8}
    now = datetime.now(UTC)
    add(1, PRICE_Q, customer="601", when=now)
    run_batch()
    due = auto.next_due(now)
    assert due is not None and 0 < due <= 0.7  # the worker wakes exactly when the quiet window ends
    assert auto.run_once(now) == {}  # still inside the quiet window
    assert auto.run_once(now + timedelta(seconds=0.75)) == {"replied": 1}
    (_, kind, send_after, _), = boxes(db)
    assert kind == "price" and (send_after - now).total_seconds() <= 0.75 + 0.8 + 0.01
    assert auto.next_due(now + timedelta(seconds=1)) is None  # nothing waiting any more


# ---------- T2 / T3 AI ----------

def test_t2_ai_in_a_pool_does_not_block_other_customers(ai, db):  # noqa: F811
    mode("auto")
    auto_on(db)

    def slow(user_input: str) -> dict:
        time.sleep(1.5)
        return ysl_answer(db)

    ai.answer = slow
    now = datetime.now(UTC) - timedelta(seconds=2)
    add(1, "ysl edp 10 ml ရောယူပါမယ်", customer="611", when=now)  # rules unsure: the AI is asked
    add(2, PRICE_Q, customer="612", when=now)  # rules sure
    run_batch()
    start = time.monotonic()
    worker.understand_with_ai()
    assert time.monotonic() - start < 0.5  # handed to the pool
    auto.run_once()
    assert [c for c, *_ in boxes(db)] == [customer_id(db, "612")]  # answered while the AI is still thinking
    wait_for_pool()
    auto.run_once()
    assert [c for c, *_ in boxes(db)] == [customer_id(db, "612"), customer_id(db, "611")]


def test_t3_ai_timeout_means_holding_reply_at_once(ai, db):  # noqa: F811
    mode("auto")
    auto_on(db)
    ai.answer = AIError("timeout")
    now = datetime.now(UTC)
    add(1, "hawas for him 10ml ယူမယ်", customer="621", when=now)  # not in the list: the AI would map it
    run_batch()
    worker.understand_with_ai()
    wait_for_pool()
    assert scalar(db, "SELECT error FROM ai_calls") == "timeout"
    auto.run_once(now + timedelta(seconds=1))
    assert holding.run_once(now + timedelta(seconds=1.5)) == {"held": 1}  # not after the 10 s safety net
    (_, kind, _, created), = boxes(db)
    assert kind == "holding"
    assert service.process(mid(db, 1, "621")) == "done already"  # no second AI answer, no double reply


# ---------- T4 needs a person ----------

def test_t4_complaint_gets_the_holding_reply_at_once_with_413_limits(shop, db):  # noqa: F811
    auto_on(db)
    now = datetime.now(UTC)
    add(1, "ပစ္စည်းယိုနေတယ်", customer="631", when=now)
    add(2, "thank you", customer="632", when=now)  # small talk: nothing
    add(3, PRICE_Q, customer="633", when=now)  # answered by itself after the quiet window: no holding
    run_batch()
    auto.run_once(now + timedelta(seconds=0.1))
    assert holding.run_once(now + timedelta(seconds=1)) == {"held": 1}
    assert [c for c, k, *_ in boxes(db) if k == "holding"] == [customer_id(db, "631")]
    add(4, "the bottle is broken", customer="631", when=now + timedelta(minutes=1))
    run_batch()
    later = now + timedelta(minutes=1, seconds=1)
    auto.run_once(later)
    assert holding.run_once(later) == {"caught": 1}  # once per 10 min (4.13)


# ---------- T5 NOTIFY + poll fallback ----------

def test_t5_notify_wakes_and_the_poll_is_the_fallback(db, monkeypatch):
    waiter = notify.Waiter("new_message")
    assert waiter.wait(0) is False  # connects + LISTEN
    add(1, "hi", customer="641")  # the trigger notifies
    start = time.monotonic()
    assert waiter.wait(5) is True and time.monotonic() - start < 1
    assert waiter.wait(0.2) is False
    waiter.conn.close()

    async def outbox_wakes() -> float:
        w = notify.AsyncWaiter("outbox")
        await w.wait(0)
        await asyncio.to_thread(_queue_reply, db)
        t = time.monotonic()
        assert await w.wait(5) is True
        await w.conn.close()
        return time.monotonic() - t

    assert asyncio.run(outbox_wakes()) < 1
    monkeypatch.setattr(notify, "_conninfo", lambda: "host=127.0.0.1 port=1 connect_timeout=1")
    broken = notify.Waiter("new_message")
    start = time.monotonic()
    assert broken.wait(0.3) is False and time.monotonic() - start < 2.5  # no crash: a plain sleep


def _queue_reply(db, kind: str = "custom", ext: int = 9) -> int:
    with db.begin() as c:
        return c.execute(text("INSERT INTO outbox (customer_id, text, reply_kind, status, idempotency_key) "
                              "VALUES (:c, 'x', :k, 'queued', :i) RETURNING id"),
                         {"c": customer_id(db, "641"), "k": kind, "i": f"k{ext}"}).scalar()


# ---------- T6 first replies first ----------

def test_t6_first_reply_before_a_reminder(db):
    add(1, "hi", customer="641")
    reminder = _queue_reply(db, "reminder", 1)
    reply = _queue_reply(db, "price", 2)
    assert reminder < reply
    assert sender.claim_next()[0] == reply
    assert sender.claim_next()[0] == reminder
    assert sender.next_due() is None
    limiter = sender.RateLimiter(clock=lambda: 100.0)
    limiter.record()
    assert limiter.wait_time() == sender.MIN_INTERVAL  # 1 message / 3 s overall is unchanged


# ---------- T7 timings ----------

def test_t7_timings_and_health_page(shop, db):  # noqa: F811
    client, token = shop
    now = datetime.now(UTC) - timedelta(minutes=5)
    add(1, "secret words 123", customer="651", when=now)
    run_batch()
    message = mid(db, 1, "651")
    with db.begin() as c:
        c.execute(text("UPDATE messages SET created_at = :t WHERE id = :m"), {"t": now + timedelta(seconds=0.3),
                                                                             "m": message})
        c.execute(text("INSERT INTO outbox (customer_id, text, reply_kind, status, idempotency_key, created_at, "
                       "sent_at) VALUES (:c, 'r', 'price', 'sent', 'k', :q, :s)"),
                  {"c": customer_id(db, "651"), "q": now + timedelta(seconds=1.5), "s": now + timedelta(seconds=2)})
    with SessionLocal() as s:
        (row,) = speed.timings(s, now - timedelta(minutes=1), now + timedelta(minutes=1))
        assert (row.message_id, row.path, round(row.total, 1)) == (message, "rules", 2.0)
        assert set(row.stages) <= set(speed.STAGES) and row.slowest in speed.STAGES
    assert speed.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9 and speed.percentile([], 50) is None
    page = client.get("/health").text
    section = page[page.index('id="speed"'):page.index("</section>", page.index('id="speed"'))]
    assert "p90" in section and "2.0 s" in section and f"#{message}" in section
    assert "secret words" not in section  # numbers and ids only
    r = client.post("/settings/auto-speed", data={"csrf": token, "quiet_s": "0.5", "delay_min_s": "0",
                                                  "delay_max_s": "0.4"}, follow_redirects=False)
    assert r.status_code == 303
    assert auto.speed(SessionLocal()) == {"quiet_s": 0.5, "delay_min_s": 0.0, "delay_max_s": 0.4}
    assert client.post("/settings/auto-speed", data={"csrf": token, "quiet_s": "0.55", "delay_min_s": "0",
                                                     "delay_max_s": "1"}).status_code == 400
