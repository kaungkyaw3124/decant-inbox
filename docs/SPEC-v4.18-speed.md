# Epic 4.18 — Speed: the first reply within 3 seconds. Build after 4.17.
Same loop (measure -> change -> test -> measure again -> deploy -> report). Commit after each part.

## GOAL
From the moment Telegram delivers a customer's message to the moment our first reply is SENT:
- rules path (we are sure without AI): **p90 ≤ 3 s**
- AI path: **p90 ≤ 5 s**; and the customer never waits more than **3 s** for SOMETHING when the message goes to
  a person (the holding reply is sent at once, not after the 60 s watchdog)
- Telegram safety rules unchanged (max 1 msg / 3 s overall, 20 / min, outbox -> listener only).

Today (planning chat reading of the code): listener -> DB -> worker polls every 1 s -> quiet window 1 s ->
AI call ~2.6 s (in the same loop, blocking everyone) -> random delay 2-3 s -> sender polls every 0.5 s.
That adds up to ~5 s (rules) and ~8-10 s (AI); the holding reply only comes from the 60 s watchdog.

## S0 Measure first (keep it permanently)
- Per incoming message store timings (new table message_timings or columns): telegram date, saved, parsed,
  AI started/finished, decided, queued, sent (first reply only). Use monotonic-safe UTC timestamps.
- /health (and /ai for the AI part): last 24 h p50 / p90 / max for rules, AI, holding; slowest 5 messages with
  which stage was slow. Numbers only, no message text.
- REPORT.md: the "before" numbers from the live DB for the last 7 days.
## S1 No more polling delays (event-driven, still only through the database)
- Postgres LISTEN/NOTIFY: the listener NOTIFYs `new_message` after insert; the worker waits on it (with the
  current 1 s poll as fallback). Inserting into outbox NOTIFYs `outbox`; the sender wakes at once (0.5 s poll
  stays as fallback). Any service may restart without losing work (the poll fallback catches up).
## S2 AI does not block others
- AI calls run in a small pool (2-4 at once) in the worker; the rules path for other customers continues
  while one waits for the AI. Start the AI call immediately when the rules are not sure (do not wait for the
  next loop). Hard AI timeout 6 s -> treat as "not sure" (holding reply + Needs you), never silence.
- Check the model setting for speed (lowest reasoning effort that keeps the eval gate; keep the eval gate).
## S3 New speed defaults (still owner-editable on /auto)
- quiet window 1 s -> 0.7 s (catches "two quick messages"); human-like delay 2-3 s -> 0.3-0.8 s.
  Allow delay minimum 0 in SPEED_LIMITS. If S0 shows customers often send 2 messages within 2 s, report it
  and keep the quiet window that wins (choose by data).
- Priority in the outbox: first replies to a waiting customer before reminders / follow-ups / payment info
  re-sends (still obeying 1 msg / 3 s overall).
## S4 Instant holding reply when a person is needed
- When the decision for a message is "a person must answer" (one-tap card, Needs you, AI not sure, timeout),
  send the holding reply right away (same 4.13 limits: once per 10 min, not after a hand reply in the last
  10 min, not for ignored / never-auto / test code). The 60 s watchdog stays as the safety net.
## S5 (Optional, OFF by default) "typing…" indicator
- Owner switch on /auto: show "typing…" in the customer's chat while we prepare an answer (Telethon
  SetTypingAction, max once per message, only in chats that wrote to us, only while Auto-reply is ON). This is a
  new Telegram action: CLAUDE.md "Hard rules" must list it as allowed before it can be switched on. Default OFF.

## Tests
T1 fake clock + fake Telegram: rules-path message -> reply queued and sent ≤ 3 s (with default speed).
T2 AI path with a 2.6 s fake AI -> sent ≤ 5 s; a second customer's rules message during that AI call is still
   answered ≤ 3 s (AI does not block).
T3 AI timeout (fake 10 s) -> holding reply ≤ 3 s + Needs you; later AI answer is ignored (no double reply).
T4 needs-person message -> holding reply ≤ 3 s; limits of 4.13 still hold (no repeat within 10 min, etc.).
T5 NOTIFY lost / worker restart -> poll fallback answers within 2 s more; nothing lost, nothing doubled.
T6 rate limit: 5 customers at once -> sends spaced ≥ 3 s, first replies first, all within 3 s × position.
T7 timings stored; /health shows p50/p90; no message text in timings.
T8 regression: full suite + 4.10 matrix + fixtures + ui gate quick mode + AI eval gate.
Deploy; then REPORT.md "after" numbers from live use (at least 20 test messages from the second account, mixed
rules / AI / person) vs the S0 "before" numbers.

## OWNER TEST 4.18
From the second account send, one by one, with a stopwatch: "hi" ; "swy intensely 5ml ယူမယ်" ; a phone ;
"ok" ; something strange ("ဟိုတစ်ခါက အနံ့လေး"). Each first reply should arrive in about 3 s (the strange one
≤ 5 s, or a holding reply ≤ 3 s). Then /health → Speed: p90 numbers.
