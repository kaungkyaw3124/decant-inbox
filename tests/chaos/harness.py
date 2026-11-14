"""docs/SPEC-v5.9-reliability-under-load.md: the chaos / stress harness.

Everything runs against a scratch database (pytest: <db>_test; scripts/load_test.py: <db>_chaos) and a FAKE
Telegram account: nothing reaches a real customer, the real session is never opened.

- FakeTelegram: records every send (virtual time); can raise TimeoutError / ConnectionError on demand, go
  offline, "crash" between claim and send or between send and mark_sent, hold messages that arrive while the
  listener is stopped, and answers the read-only calls the listener uses (get_messages, get_dialogs).
- Listener: the real sender loop + gap fill + message handler in an asyncio loop of its own thread.
- Worker: the real parser worker main loop (app/parser/worker.py main) in a thread.
- The send rate limiter runs on a virtual clock (SPEED x real time) so tests are fast; the limits are the real
  ones in virtual time (scripts/load_test.py --real runs them at real speed).
"""
import asyncio
import statistics
import sys
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import text
from telethon.tl import types

from app.core.db import SessionLocal
from app.listener import main as listener_main
from app.listener import sender
from app.listener.save import from_telethon
from app.orders import holding
from app.parser import worker

SPEED = 60.0  # 1 real second = 60 virtual seconds for the send limiter (3 s between sends -> 0.05 s)
FIRST_USER = 700000
REPLY_WITHIN = 60.0


CODE = "Chaos2468x"  # the test payment code of these runs only


def flow(uid: int) -> list[str]:
    """One customer's normal order: price question -> cart -> phone -> address (-> payment info) -> "ok" -> code."""
    return ["stw intensely 5ml ဘယ်လောက်လဲ", "stw intensely 5ml ယူမယ်", f"09{uid % 10**9:09d}"[:11],
            "အမှတ် 12, ဗိုလ်ချုပ်လမ်း, လှိုင်မြို့နယ်, ရန်ကုန်", "ok", CODE]


class Crash(BaseException):
    """The listener process dies right here (not an Exception: nothing in the app catches it)."""


class FakeTelegram:
    def __init__(self, speed: float = SPEED):
        self.speed, self.t0 = speed, time.monotonic()
        self.next_id = 5000
        self.history: dict[int, list[types.Message]] = defaultdict(list)  # user id -> messages, oldest first
        self.users: dict[int, types.User] = {}
        self.sent: list[tuple[float, int, str, int, float]] = []  # (virtual time, user, text, message id, real)
        self.connected = True
        self.fail = None  # fail(user id, attempt number) -> exception to raise, or None
        self.crash: str | None = None  # "before" | "after": the next send crashes the listener there
        self.attempts = 0
        self.handler = None  # the listener's message handler while it runs
        self.loop: asyncio.AbstractEventLoop | None = None

    # ---- clocks
    def vclock(self) -> float:
        return (time.monotonic() - self.t0) * self.speed

    # ---- what the app calls
    def is_connected(self) -> bool:
        return self.connected

    async def get_input_entity(self, peer):
        if not self.connected:
            raise ConnectionError("offline")
        return peer

    async def send_message(self, entity, message, link_preview=False):
        if not self.connected:
            raise ConnectionError("offline")
        self.attempts += 1
        if self.crash == "before":
            self.crash = None
            raise Crash()
        if self.fail and (exc := self.fail(entity.user_id, self.attempts)):
            raise exc
        m = self._add(entity.user_id, message, out=True)
        self.sent.append((self.vclock(), entity.user_id, message, m.id, time.monotonic()))
        if self.crash == "after":
            self.crash = None
            raise Crash()
        if self.handler is not None:  # Telegram also delivers our own message as an "out" update
            asyncio.get_running_loop().create_task(self.handler(m, self.users[entity.user_id]))
        return m

    async def get_messages(self, entity, limit=20):
        if not self.connected:
            raise ConnectionError("offline")
        uid = getattr(entity, "user_id", None) or entity.id
        return list(reversed(self.history[uid]))[:limit]  # newest first, as Telethon

    async def get_dialogs(self, limit=30):
        if not self.connected:
            raise ConnectionError("offline")
        recent = sorted(self.history, key=lambda u: self.history[u][-1].id, reverse=True)[:limit]
        return [SimpleNamespace(entity=self.users[u], is_user=True) for u in recent]

    # ---- the test side
    def user(self, uid: int) -> types.User:
        if uid not in self.users:
            self.users[uid] = types.User(id=uid, first_name="Chaos", last_name=str(uid))
        return self.users[uid]

    def _add(self, uid: int, body: str, out: bool) -> types.Message:
        self.user(uid)
        self.next_id += 1
        m = types.Message(id=self.next_id, peer_id=types.PeerUser(uid), date=datetime.now(UTC), message=body, out=out)
        self.history[uid].append(m)
        return m

    async def incoming(self, uid: int, body: str) -> types.Message:
        """A customer writes to the shop account (saved only if the listener runs, else held by Telegram)."""
        m = self._add(uid, body, out=False)
        if self.handler is not None:
            await self.handler(m, self.users[uid])
        return m

    def sent_to(self, uid: int) -> list[str]:
        return [t for _, u, t, *_ in self.sent if u == uid]

    def max_per_minute(self) -> int:
        times = sorted(t for t, *_ in self.sent)
        best, j = 0, 0
        for i, t in enumerate(times):
            while times[j] <= t - 60:
                j += 1
            best = max(best, i - j + 1)
        return best


class FastLimiter(sender.RateLimiter):
    """The real limits on the fake's virtual clock; waits are real seconds (virtual / SPEED)."""

    def __init__(self, fake: FakeTelegram):
        super().__init__(clock=fake.vclock)
        self.fake = fake

    def wait_time(self) -> float:
        return super().wait_time() / self.fake.speed


async def _old_handler(message, chat) -> None:  # the commit-b663059 listener had no module-level handler
    msg = from_telethon(message, chat)
    if msg is None:
        return
    try:
        await asyncio.to_thread(listener_main._save, msg)
    except Exception:
        pass  # logged and dropped, as the old on_message did


class Listener:
    """The listener process: message handler + sender loop + gap fill, in its own event loop thread."""

    def __init__(self, fake: FakeTelegram, gap_every: float = 300.0, poll: float = 0.05):
        self.fake, self.gap_every, self.poll = fake, gap_every, poll
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        fake.loop = self.loop
        self.tasks: list[asyncio.Future] = []

    def run(self, coro, timeout: float | None = None):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def start(self) -> None:
        async def go():
            self.fake.handler = getattr(listener_main, "on_new_message", _old_handler)
            tasks = [asyncio.ensure_future(sender.run_forever(self.fake, poll_seconds=self.poll))]
            if hasattr(listener_main, "fill_gaps_forever"):
                tasks.append(asyncio.ensure_future(listener_main.fill_gaps_forever(self.fake, self.gap_every)))
            return tasks
        self.tasks = self.run(go())

    def alive(self) -> bool:
        return bool(self.tasks) and all(not t.done() for t in self.tasks)

    def stop(self) -> None:
        async def go():
            self.fake.handler = None
            for t in self.tasks:
                t.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.run(go())
        self.tasks = []

    def close(self) -> None:
        if self.tasks:
            self.stop()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


class _Stop(BaseException):
    pass


class Worker:
    """app/parser/worker.py main() in a thread (the same loop the systemd service runs)."""

    def __init__(self, monkeypatch, interval: float = 0.2):
        self.stopping = threading.Event()
        self.error: BaseException | None = None
        real = worker.Waiter
        stopping = self.stopping

        class StoppableWaiter(real):
            def wait(self, timeout):
                if stopping.is_set():
                    raise _Stop()
                return super().wait(min(timeout, 0.2))

        monkeypatch.setattr(worker, "Waiter", StoppableWaiter)
        monkeypatch.setattr(sys, "argv", ["worker", "--interval", str(interval)])
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            worker.main()
        except _Stop:
            pass
        except BaseException as exc:  # noqa: BLE001 — reported by the test
            self.error = exc

    def start(self) -> "Worker":
        self.thread.start()
        return self

    def stop(self, timeout: float = 180) -> None:
        self.stopping.set()
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "worker did not stop"


def run_flows(chaos, uids: list[int], steps: int | None = None, within: float = REPLY_WITHIN) -> dict[int, dict]:
    """Every customer runs flow() at the same moment, each next message after our reply (small talk "ok"
    needs none). Returns per customer: first / last reply seconds, per-message waits, missing replies."""
    out = {uid: {"waits": [], "missing": [], "first": None, "last": None} for uid in uids}

    async def customer(uid: int) -> None:
        start = time.monotonic()
        for body in chaos.flow(uid)[:steps]:
            before = len(chaos.fake.sent_to(uid))
            m = await chaos.fake.incoming(uid, body)
            asked = time.monotonic()
            if not holding.is_small_talk(body):
                while len(chaos.fake.sent_to(uid)) == before and time.monotonic() - asked < within:
                    await asyncio.sleep(0.05)
                got = time.monotonic()
                if len(chaos.fake.sent_to(uid)) == before:
                    out[uid]["missing"].append(body[:20])
                out[uid]["waits"].append(got - asked)
                out[uid]["first"] = out[uid]["first"] or got - start
            # like a person: read "please wait", wait for the real answer (the message decided, nothing queued)
            while time.monotonic() - asked < within and not await asyncio.to_thread(_settled, uid, m.id):
                await asyncio.sleep(0.5)
            if len(chaos.fake.sent_to(uid)) > before:
                out[uid]["last"] = time.monotonic() - start
            await asyncio.sleep(0.3)  # the customer reads our reply

    async def everyone():
        await asyncio.gather(*(customer(uid) for uid in uids))

    chaos.listener.run(everyone())
    return out


def _settled(uid: int, telegram_id: int) -> bool:
    """The shop is done with this message: decided by auto mode (or the test code taken), nothing to send."""
    return bool(scalar(
        "SELECT (EXISTS (SELECT 1 FROM auto_runs r WHERE r.message_id = m.id) "
        "     OR EXISTS (SELECT 1 FROM audit_log a WHERE a.action LIKE 'test_code.%' "
        "                AND (a.details->>'message_id')::int = m.id)) "
        "AND NOT EXISTS (SELECT 1 FROM outbox o WHERE o.customer_id = m.customer_id AND o.status IN ('queued', 'sending')) "
        "FROM messages m WHERE m.external_chat_id = :u AND m.external_message_id = :t",
        u=str(uid), t=str(telegram_id)))


def wait_until(check, timeout: float, every: float = 0.1) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(every)
    return check()


def scalar(sql: str, **params):
    with SessionLocal() as s:
        return s.execute(text(sql), params).scalar()


def rows(sql: str, **params) -> list:
    with SessionLocal() as s:
        return list(s.execute(text(sql), params))


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))] if ordered else 0.0


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def assert_invariants(fake: FakeTelegram | None = None, since: datetime | None = None, connected: bool = True) -> None:
    """docs/SPEC-v5.9: checked after every chaos test."""
    from app.orders import holding
    from app.web.auto import for_customer, needs_you

    since = since or datetime.now(UTC) - timedelta(hours=2)
    problems = []
    unparsed = scalar("SELECT count(*) FROM messages m WHERE m.direction = 'in' AND m.received_at >= :s "
                      "AND m.created_at < now() - interval '60 seconds' AND NOT EXISTS (SELECT 1 FROM parse_results p "
                      "WHERE p.message_id = m.id AND p.is_current)", s=since)
    if unparsed:
        problems.append(f"{unparsed} inbound messages without a current parse result for > 60 s")
    with SessionLocal() as s:
        found = needs_you(s)
        from app.models import Message

        newest = s.execute(text(
            "SELECT DISTINCT ON (customer_id) id FROM messages WHERE direction = 'in' AND kind = 'text' "
            "AND received_at >= :s AND created_at < now() - interval '60 seconds' "
            "ORDER BY customer_id, received_at DESC, id DESC"), {"s": since}).scalars().all()
        for mid in newest:
            m = s.get(Message, mid)
            if holding.is_small_talk(m.raw_text) or holding._answered(s, m):
                continue
            if for_customer(found, m.customer_id).get("count"):
                continue
            problems.append(f"message {mid} of customer {m.customer_id} unanswered, not in Needs you, for > 60 s")
    claimed = "coalesce(claimed_at, created_at)" if scalar(  # (the proof run on commit b663059 has no claimed_at)
        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'outbox' AND column_name = 'claimed_at'") \
        else "created_at"
    stuck = scalar(f"SELECT count(*) FROM outbox WHERE status = 'sending' AND {claimed} < now() - interval '2 minutes'")
    if stuck:
        problems.append(f"{stuck} outbox rows 'sending' for > 2 min")
    if connected:
        old = scalar("SELECT count(*) FROM outbox WHERE status = 'queued' AND send_after < now() - interval '5 minutes'")
        if old:
            problems.append(f"{old} outbox rows queued for > 5 min")
    if fake is not None:
        seen, ids = set(), set()
        for _, uid, body, mid, real in fake.sent:
            key = (uid, body, int(real // 60))
            if key in seen:
                problems.append(f"duplicate send to {uid} in one minute: {body[:40]!r}")
            seen.add(key)
            if mid in ids:
                problems.append(f"message id {mid} twice")
            ids.add(mid)
    dup = scalar("SELECT count(*) FROM (SELECT 1 FROM messages GROUP BY channel, external_chat_id, external_message_id "
                 "HAVING count(*) > 1) d")
    if dup:
        problems.append(f"{dup} duplicate messages")
    assert not problems, "invariants broken:\n" + "\n".join(problems)


def open_shop(monkeypatch, speed: float = SPEED, gap_every: float = 2.0, short_timers: bool = True) -> SimpleNamespace:
    """The live shop's setup on the (empty, scratch) database + a fake Telegram + the listener (not started)."""
    from datetime import timedelta as _td

    from pydantic import SecretStr

    from app.core.config import get_settings
    from app.models import Customer, User
    from app.orders import auto, testpay
    from scripts.simulate import prepare_shop

    prepare_shop()
    with SessionLocal.begin() as s:
        owner = User(username="owner", password_hash="x", role="owner")
        s.add(owner)
        s.flush()
        testpay.set_auto_approve(s, True, owner)
    monkeypatch.setattr(auto, "DAILY_CAP", 100_000)  # shortcut: as the simulator, the daily cap is not tested here
    monkeypatch.setattr(get_settings(), "test_pay_code", SecretStr(CODE))
    if short_timers:  # stuck after 1 s, recovery every 1 s, retries after 0.2 / 0.4 / 0.6 s
        monkeypatch.setattr(sender, "STUCK_AFTER", _td(seconds=1), raising=False)
        monkeypatch.setattr(sender, "RECOVER_EVERY", 1.0, raising=False)
        monkeypatch.setattr(sender, "RETRY_DELAYS", (0.2, 0.4, 0.6), raising=False)
    fake = FakeTelegram(speed)
    monkeypatch.setattr(sender, "RateLimiter", lambda clock=None: FastLimiter(fake))
    listener = Listener(fake, gap_every=gap_every)
    workers: list[Worker] = []

    def customers(n: int, tester: bool = True) -> list[int]:
        uids = [FIRST_USER + i for i in range(n)]
        with SessionLocal.begin() as s:
            for uid in uids:
                s.add(Customer(channel="telegram", external_user_id=str(uid), display_name=f"Chaos {uid}",
                               is_tester=tester))
        for uid in uids:
            fake.user(uid)
        return uids

    def start_worker() -> Worker:
        w = Worker(monkeypatch).start()
        workers.append(w)
        return w

    def close() -> None:
        for w in workers:
            if w.thread.is_alive():
                w.stop()
        listener.close()

    return SimpleNamespace(fake=fake, listener=listener, customers=customers, start_worker=start_worker,
                           workers=workers, monkeypatch=monkeypatch, main=listener_main, flow=flow, close=close)
