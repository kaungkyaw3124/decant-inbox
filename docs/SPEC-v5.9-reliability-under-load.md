# v5.9 — Reliability under load: no lost message, no silent customer, proven by a stress test. Goal-driven loop.
Owner 2026-11-14: another system lost output under a burst (a thermal printer printed 7-8 of 14 items). Find the
same class of bug here. The planning chat read the code and found the 7 problems below (NOT yet reproduced:
reproduce each with a failing test FIRST, then fix). Telegram safety rules in CLAUDE.md stay: all tests use a FAKE
Telegram client and a scratch database; nothing reaches a real customer; the send rate limits are not raised.

## Problems to prove and fix (file refs from the planning chat's read)
B1 HIGH  Stuck "sending" = silent customer. sender.py claim_next() commits status "sending" BEFORE the send; a crash /
         restart / deploy in between leaves it "sending" forever, never retried (models/outbox.py says so on
         purpose). holding.py `_answered` (line ~57) and `followups`, `auto` treat "sending" as answered, so the
         60 s silence watchdog never fires. Fix: recovery sweep at listener start and every minute for rows
         "sending" older than 90 s: look in Telegram (read-only get_messages of that chat, last 20 outgoing) for the
         same text sent after the row was claimed -> mark sent (record the message); not found -> back to "queued"
         (once; attempts counter) ; cannot tell (offline) -> leave and alert. The watchdog must not count a
         "sending" row older than 2 min as an answer. Never a double send.
B2 HIGH  A message that fails to save is lost. listener/main.py on_message logs and drops it; the comment says
         import_history fills gaps but nothing runs it. Fix: retry the save 3x (backoff 0.5/1/2 s); AND an automatic
         gap-fill every 5 min and at start: read the last 30 messages of the 30 most recently active private chats
         (read-only) and save any missing ones with the same idempotent save_message(); log counts only. Messages
         saved late are parsed and answered as normal.
B3 HIGH  A transient send error fails the reply for good. sender.py `except Exception` -> status "failed", no retry,
         no alert. Fix: retry network / timeout / Telegram server errors up to 3 times with backoff (10 s, 30 s,
         90 s; stays "queued" with send_after), permanent errors (privacy, blocked, peer invalid) fail at once; a
         reply that finally fails creates a Needs-you item "reply to <customer> failed" and an owner alert (new
         alert type "send_failed", 5.0 bot, deduped); the silence watchdog sends nothing more to a customer whose
         last reply failed permanently.
B4 MED   Whole-history re-parse inside the worker loop. worker.py reparse_if_catalog_changed -> reparse_all() over
         every customer message ever, on any alias / learned-phrase change (auto-learning triggers it). The same
         loop (auto replies, AI, watchdog, heartbeat) stops meanwhile; and catalog_fingerprint() reloads 4 tables on
         every wake-up. Fix: re-parse only messages newer than 14 days or without a human/AI result, in chunks of
         100 with `auto.run_once()` / watchdog / heartbeat between chunks (or a separate low-priority thread); a
         cheap fingerprint (max(updated_at) + count per table, one query). The full re-parse stays available as the
         script.
B5 MED   One worker, batch first. worker.py: run_batch() handles up to 200 messages and `continue`s before payments,
         auto replies and the watchdog run. Fix: time-box the batch (≈ 2 s or 50 messages), then run the rest of the
         loop each round.
B6 MED   Global send capacity with no visibility. sender.py: 1 send / 3 s and 20 / min for ALL customers (keep the
         limits). Fix: fairness (one customer's burst of replies does not delay every other customer: serve by
         oldest-waiting customer, replies to a customer in order); /health shows queue length + age of the oldest
         queued reply; alert type "queue" when the oldest queued reply is older than 90 s (resolved line when
         empty); a customer's reply is ONE message wherever possible (already true for payment info).
B7 MED   Database pool and per-tab polling. core/db.py create_engine uses the default pool (5 + 10 overflow) while the
         web server runs ~40 threads; each open dashboard tab runs snapshot() every 2 s (incl. needs_count) and
         holds its own Postgres connection for NOTIFY (web/live.py). Fix: pool_size 20 / max_overflow 20 /
         pool_timeout 10 for web, 10 / 10 for worker and listener; ONE shared snapshot per 2 s for all streams
         (background task + fan-out), max 3 streams per user; a pool-exhaustion log line + /health counter.
Also check (report, fix if real): parser `_failed` messages are never retried until restart and need a Needs-you
item (worker.py line ~57); outbox rows refused by claim_next return "nothing" and delay the next claim by up to 0.5 s.

## The stress tests (tests/chaos/ + scripts/load_test.py; scratch DB `<db>_chaos`, fake Telegram client)
FakeTelegram: records every send with a timestamp; can raise TimeoutError / ConnectionError / FloodWait on demand,
drop the connection, "crash" (cancel the sender task between claim and send, and between send and mark_sent),
replay missed updates, and expose a sent-history for the B1 check. A virtual clock may be used for the rate
limiter so the tests are fast, plus ONE real-time run at the real limits (documented duration).
T1 Burst: 50 customers each send the normal order flow (price question → cart → phone → address → "yes" → test
   code) at the same moment. Pass: every message answered or a Needs-you card within 60 s (real-time run: within
   the limits), 0 lost, 0 duplicates, order numbers unique, stock deducted once, total sends ≤ 20 / min, no
   customer waits more than 2× the median.
T2 Timing: record time to FIRST reply and to LAST reply per customer; report p50 / p90 / max in REPORT.md (this is
   the capacity number: how many customers per minute the shop can serve).
T3 Crash while sending (twice: before the send, after the send): restart → each reply is sent exactly once
   (verified in the fake sent-history), none stuck in "sending".
T4 Transient errors: every 5th send times out → all replies arrive after retries; 3 failures in a row → "failed"
   + Needs-you + alert row, and no further automatic message to that customer.
T5 Database down 20 s (stop accepting connections / raise OperationalError) while 20 messages arrive → all saved
   after it returns (retry + gap-fill), none lost, no crash loop.
T6 Missed messages: stop the listener, deliver 40 messages to the fake account, start it → all saved within the
   gap-fill interval (shortened in the test).
T7 Big history: 5,000 old messages + 20 new while an alias is edited → live replies still go out ≤ 5 s; the worker
   heartbeat never goes older than 60 s.
T8 Tabs: 20 SSE streams + 30 page requests at once during T1 → no pool errors, p90 page time ≤ 1 s, DB connections
   ≤ the configured pool.
T9 Double click: approve the same payment check from 10 threads → one order number, one stock deduction, one
   "paid" message.
Invariants checked after EVERY test (helper `assert_invariants(db)`): no inbound message without a current parse
result older than 60 s; no customer message unanswered / without Needs-you / review for > 60 s (except small
talk); no outbox row "sending" older than 2 min; no row "queued" older than 5 min while the fake is connected; no
duplicate (customer, text, minute) in the fake sent-history; message ids unique.
The existing 917 tests, the simulator quick run and ui_check must stay green. New tests must FAIL on the code of
commit b663059 for B1, B2, B3, B4, B5, B7 (prove it by running them first and listing the failures in REPORT.md).

## GOAL (loop until all true)
- **R1** T1-T9 pass with the invariants, on the fixed code; each fails on the old code as stated above.
- **R2** T2 numbers are in REPORT.md, with the capacity statement ("N customers per minute at the current limits").
- **R3** /health shows queue length + oldest age; alerts "send_failed" and "queue" work (fake bot) and appear in
  Settings → Alerts.
- **R4** Owner test below passes on the live system. **R5** Full suite, simulator quick run, ui_check green.

## Loop
Write the failing tests -> list which fail (proof) -> fix the biggest -> run T1-T9 + full suite -> repeat until R1-R5.
Do not lower the goal, skip, delete or xfail tests. One line per loop in REPORT.md "5.9 scoreboard" (loop, chaos
tests failing, invariants broken, p90 time to last reply). Back up the database before any migration. Deploy and
restart the services in the same step; stop only for something the owner must decide.
Chaos tests never run against the live database or the real Telegram session.

## OWNER TEST 5.9 (live system, second Telegram account; about 15 minutes)
1. /health: the new "Reply queue" line shows 0 waiting.
2. From the second account send 5 short messages in a row ("price stw intensely 5ml", "10ml?", "ok", …): every one gets
   a reply within about a minute; none is missing in the chat.
3. Send "price aventus 10ml". While the reply is waiting (send it and quickly run in the server terminal
   `systemctl --user restart decant-listener`) → the reply still arrives once (not twice, not never).
4. Run `systemctl --user stop decant-listener`, send 3 messages from the second account, wait 2 minutes, run
   `systemctl --user start decant-listener` → within 6 minutes all 3 messages show in the dashboard and are answered.
5. /health shows no "stuck" replies. Settings → Alerts lists "Reply failed" and "Reply queue long".
