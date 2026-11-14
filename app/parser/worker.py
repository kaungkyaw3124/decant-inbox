"""Parser worker: parses messages that have no current parse result yet.

Talks to the other services only through the database, so it can restart at any
time; on start it simply catches up on everything still unparsed.

Usage: .venv/bin/python -m app.parser.worker [--once]
Logs only ids and counts, never message text.
"""
import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.ai import graduation, screens, service as ai
from app.core.db import SessionLocal
from app.core.heartbeat import beat
from app.core.notify import Waiter, notify
from app.models import Message
from app.learning import patterns
from app.orders import auto, cart, delivery, followups, holding, payments, testpay
from app.parser.rules import PARSER_VERSION
from app.parser.service import (
    load_aliases, load_full_sizes, load_known_words, load_phrases, parse_message, unparsed_message_ids,
)
from scripts.reparse_all import reparse_all

log = logging.getLogger("parser")
BATCH = 50  # docs/SPEC-v5.9 B5: a batch is time-boxed, then the replies / watchdog run
BATCH_SECONDS = 1.0
HEARTBEAT_SECONDS = 30
HOUSEKEEPING_SECONDS = 600
FOLLOWUP_SECONDS = 60
REPARSE_DAYS = 14  # docs/SPEC-v5.9 B4: older messages keep their result (scripts/reparse_all.py does all)
REPARSE_CHUNK = 20  # ~70 ms per message: a chunk holds live customers up ~1.5 s at most
RETRY_FAILED = 600.0  # a message that failed to parse is tried again after 10 min (it waits in Needs you)
_failed: dict[int, float] = {}  # message id -> monotonic time of the failure
more_waiting = False  # the last run_batch() stopped early (time box / full batch): loop again without sleeping


def run_batch(live_only: bool = False) -> int:
    """Parse up to BATCH unparsed messages (at most ~BATCH_SECONDS). Returns how many were parsed.
    live_only: only messages of the last 10 minutes (between the chunks of a re-parse)."""
    global more_waiting
    started = time.monotonic()
    more_waiting = False
    for message_id in [m for m, at in _failed.items() if started - at >= RETRY_FAILED]:
        del _failed[message_id]
    with SessionLocal() as session:
        ids = unparsed_message_ids(session, BATCH, set(_failed), live_only)
        if not ids:
            return 0
        aliases = load_aliases(session)  # reloaded per batch: dashboard may add aliases
        full_sizes = load_full_sizes(session)
        known_words = load_known_words(session)
        phrases = load_phrases(session)
    done = 0
    more_waiting = len(ids) == BATCH
    for message_id in ids:
        try:
            with SessionLocal.begin() as session:
                parse_message(session, session.get(Message, message_id), aliases, full_sizes, known_words, phrases)
            done += 1
        except IntegrityError:
            log.info("message=%s already parsed by another process", message_id)
        except Exception:
            _failed[message_id] = time.monotonic()
            log.exception("failed to parse message=%s", message_id)
        if time.monotonic() - started >= BATCH_SECONDS:
            more_waiting = True
            break
    return done


# Everything the parser reads (products, aliases, learned patterns): one query, a hash made by Postgres
_FINGERPRINT = text("""SELECT md5(
  coalesce((SELECT string_agg(concat_ws(',', id, brand, name, active, full_size_ml), '|' ORDER BY id)
            FROM products), '') || '#' ||
  coalesce((SELECT string_agg(concat_ws(',', id, product_id, normalized_alias), '|' ORDER BY id)
            FROM product_aliases), '') || '#' ||
  coalesce((SELECT string_agg(concat_ws(',', id, kind, normalized_text, product_id, intent, status), '|' ORDER BY id)
            FROM learned_patterns WHERE kind <> 'not_stocked'), ''))""")


def catalog_fingerprint() -> str:
    with SessionLocal() as session:
        return session.scalar(_FINGERPRINT)


def reparse_if_catalog_changed(last: str | None, between=None) -> str:
    """Products/aliases edited in the dashboard (or re-seeded) -> re-parse the last REPARSE_DAYS days, in chunks,
    with between() (the live round) after each chunk. Also runs once at start, to catch changes made while the
    worker was down."""
    current = catalog_fingerprint()
    if current != last:
        stats = reparse_all(since=datetime.now(UTC) - timedelta(days=REPARSE_DAYS), chunk=REPARSE_CHUNK,
                            between=between)
        log.info("catalog changed, re-parsed: %s", dict(stats))
    return current


def scan_payments() -> None:
    """Payment screenshots -> payment checks (Step 5); the test payment code (docs/SPEC-v4.14)."""
    try:
        with SessionLocal.begin() as session:
            found = payments.scan(session)
        if found:
            log.info("payment photos: %d new/changed checks", found)
    except Exception:
        log.exception("payment scan failed")
    try:
        with SessionLocal.begin() as session:
            codes, approved = testpay.scan(session), testpay.run_auto_approve(session)
        if codes or approved:
            log.info("test payments: %d code messages, %d auto-approved", codes, approved)
    except Exception:
        log.exception("test payment step failed")


def housekeeping() -> None:
    """Carts idle for 3 days -> abandoned; sent out N days ago -> delivered (DB-only chores;
    this worker runs 24/7 anyway)."""
    with SessionLocal.begin() as session:
        abandoned = cart.abandon_idle(session)
        delivered = delivery.auto_deliver(session)
    if abandoned or delivered:
        log.info("abandoned %d idle carts, %d orders auto-delivered", abandoned, delivered)


def follow_up() -> None:
    """Payment reminders and auto-cancel of unpaid orders (docs/SPEC-v3.md 6.2); feedback after delivery
    (docs/SPEC-v5.2 P3, only when switched on)."""
    try:
        with SessionLocal.begin() as session:
            stats = followups.run(session)
        if stats:
            log.info("payment follow-ups: %s", stats)
    except Exception:
        log.exception("payment follow-ups failed")
    try:
        from app import care  # late import

        with SessionLocal.begin() as session:
            if asked := care.ask_feedback(session):
                log.info("feedback asked: %d orders", asked)
    except Exception:
        log.exception("feedback step failed")


def catch_silence() -> None:
    """docs/SPEC-v4.13-hotfix.md Q1: a waiting customer never gets silence (holding reply after 60 s)."""
    try:
        stats = holding.run_once()
        if stats:
            log.info("holding replies: %s", stats)
    except Exception:
        log.exception("silence watchdog failed")


def read_screenshots() -> None:
    """docs/SPEC-v4.12-address-payment-ai.md N3: payment screenshots an admin opened, when the owner turned
    screenshot reading on."""
    try:
        stats = screens.run_once()
        if stats:
            log.info("screenshots: %s", stats)
    except Exception:
        log.exception("screenshot reading failed")


AI_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ai")  # docs/SPEC-v4.18 S2
_asking: set[int] = set()  # message ids the pool is asking the AI about now (this process)


def _ask(message_id: int) -> None:
    """In a pool thread: one AI call; then wake the main loop so the auto reply goes out at once."""
    try:
        stats = {ai.process_safe(message_id): 1}
        ai.check_brake(datetime.now(UTC), stats)
        log.info("AI message=%s: %s", message_id, stats)
    finally:
        _asking.discard(message_id)
        try:
            notify("new_message", "ai")
        except Exception:
            log.warning("could not wake the worker after the AI answer")


def understand_with_ai() -> None:
    """docs/SPEC-v4.6-ai.md: messages the rules are not sure about (before auto mode looks at them), asked in
    a small pool so a slow AI call never holds up other customers (docs/SPEC-v4.18 S2).
    docs/SPEC-v4.7-graduation.md: daily graduation / brake check and the weekly summary."""
    try:
        for message_id in ai.pending():
            if message_id not in _asking:
                _asking.add(message_id)
                AI_POOL.submit(_ask, message_id)
    except Exception:
        log.exception("AI step failed")
    try:
        for line in graduation.tick():
            log.info("AI graduation: %s", line)
    except Exception:
        log.exception("AI graduation check failed")


def sleep_for(interval: float) -> float:
    """docs/SPEC-v4.18 S1: until the next poll, or until a waiting customer's quiet window ends."""
    try:
        due = auto.next_due(datetime.now(UTC))
    except Exception:
        log.exception("next_due failed")
        due = None
    return interval if due is None else min(interval, max(due, 0.05))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="parse what is pending, then exit")
    # 1 s fallback poll; a NOTIFY (new message, AI answer) or the end of a quiet window wakes it earlier
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between polls")
    args = parser.parse_args()

    log.info("parser worker started (%s)", PARSER_VERSION)
    waiter = Waiter("new_message")
    fingerprint = None
    last_beat = last_chores = last_follow_up = 0.0

    def live_round(live_only: bool = False) -> int:
        """New messages, payments, AI, auto replies, the silence watchdog, the heartbeat. Also between the
        chunks of a re-parse (live_only: no backlog then), so live customers never wait for it (docs/SPEC-v5.9
        B4/B5)."""
        nonlocal last_beat
        if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
            beat("parser", PARSER_VERSION)
            last_beat = time.monotonic()
        parsed = run_batch(live_only)
        if parsed:
            log.info("parsed %d messages", parsed)
        scan_payments()
        read_screenshots()
        understand_with_ai()
        auto.run_once()  # auto mode (does nothing while it is switched off)
        catch_silence()
        return parsed

    while True:
        if time.monotonic() - last_chores >= HOUSEKEEPING_SECONDS:
            housekeeping()
            last_chores = time.monotonic()
        if time.monotonic() - last_follow_up >= FOLLOWUP_SECONDS:
            follow_up()
            last_follow_up = time.monotonic()
        try:
            fingerprint = reparse_if_catalog_changed(fingerprint, lambda: live_round(live_only=True))
        except Exception:
            log.exception("re-parse failed")
        parsed = live_round()
        if more_waiting:
            continue  # more are waiting: no sleep (the rest of the round ran already)
        if args.once:
            if parsed:
                continue
            AI_POOL.shutdown(wait=True)
            return
        waiter.wait(sleep_for(args.interval))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
