# v5.7 — (A) Date filter chips on the list pages, (B) light chat: load 20 messages, older on demand. Goal-driven loop.
Owner 2026-11-08: "add date in orders like a filter — option 1 (quick chips)" and "when a chat is open it loads
everything; that reduces performance. Load the first 10-20 messages, and when I pull up, load more above."
Keep it simple: no new settings, no new pages. PC first; phone must keep working (ui_check green).

## What the planning chat found (confirm in M0)
- app/web/chats.py: THREAD_SIZE = 100 messages are loaded and rendered every time a chat opens, and _thread.html
  re-renders the WHOLE thread every 4 s (`hx-trigger="every 4s" hx-swap="outerHTML"`), including photos/payment
  state lookups. That is the cost the owner feels. (5.3 may have added live updates: reuse them if present.)
- Orders page shows only age ("21 d"), no date, no date filter.

## A. Date filter chips (Orders first; same component on Payments, Customers, Sales)
- One shared macro + backend helper `date_range(request)` (like the 5.4 pager): chips row
  **Today · Yesterday · 7 days · 30 days · All time · Pick dates…** next to the status tabs. "Pick dates…" opens a
  small from–to calendar (native `<input type=date>` ×2 + Apply is enough; no library).
- URL: `?range=today|yesterday|7d|30d|all` or `?from=YYYY-MM-DD&to=YYYY-MM-DD`; works with Back, links, the pager
  and the status tabs; changing the range resets the page to 1. Default = All time (today's behaviour), except
  Sales keeps its current default.
- Dates are the SHOP's day in Asia/Yangon (UTC+06:30), not UTC: "Today" starts at 00:00 Yangon time.
  Which date: Orders = date the order was created; Payments = date the screenshot arrived; Customers = date of
  the last message; Sales = date the order was paid (reuse the existing logic if Sales already has a range).
- Status-tab counts (Unpaid · Check · To pack · …) and totals follow the chosen dates. A small line under the
  chips: "Showing 12 orders · 6 Nov – 8 Nov" with "Clear" when a range is set.
- Every order row shows its real date and time ("8 Nov, 3:12 pm") next to the age ("21 d"). Burmese UI: same
  numbers, month names translated; add keys to i18n_my.py.
- Invalid or reversed dates: swap them / ignore with a friendly message, never an error page.

## B. Light chat
- Opening a chat renders only the **last 20 messages** (setting stays in code, `THREAD_SIZE = 20`), scrolled to the
  bottom. Day separators and bubbles unchanged.
- **Older messages on demand:** scroll to the top (IntersectionObserver / `hx-trigger="revealed"`) or press the
  small "Load older messages" button at the top: fetch the 20 messages before the oldest shown
  (`/chats/<id>/thread?before=<message_id>&limit=20`), prepend them, and **keep the scroll position** (the
  bubble you were reading must not jump). When no more: "Beginning of the conversation". Day separator is not
  duplicated at the seam.
- **No more 4-second full re-render:** the open chat asks the server for changes cheaply — `?after=<last id>`
  returns only NEW bubbles (appended; if the owner is scrolled up, show a small "New message ↓" pill instead of
  jumping) — plus updated state for the few bubbles that can still change (sending → sent/failed, "Sending in N s
  · Cancel", payment check status, photo download): the server sends them only when their version changed
  (ETag / `204 No Content` when nothing changed). If 5.3 SSE exists, use it for the "something changed" signal.
- Lists in the thread that were built for 100 messages (sent_by(), albums, AI reasons, payment checks, downloads)
  are queried only for the messages being rendered.
- Opening a chat from the list = no full page reload (5.3 hx-boost); first paint of the thread ≤ 300 ms server
  time on the live data (Server-Timing from 5.3), and ≤ 20 bubble nodes initially.
- Search "jump to message" links (`#m123`) still work: if the target is older than the window, load enough pages
  before it, then scroll to it.

## GOAL (loop until all true)
- **D1** On Orders, Payments, Customers and Sales the chips filter correctly (Yangon day boundaries, tabs counts
  and pager follow), the URL is shareable, Back works, rows show the date. Tests with fixed clocks around
  23:59 / 00:00 Yangon time and the UTC date change (17:30 UTC).
- **D2** Opening any chat renders ≤ 20 messages and its server time is ≤ 200 ms p90 even for a customer with
  500+ messages (seed a test customer with 600 messages + photos + orders).
- **D3** Scrolling up loads older messages 20 at a time, keeps the scroll position, never duplicates or skips a
  message, ends cleanly at the first message.
- **D4** The open chat sends no full-thread HTML every 4 s any more: when nothing changed the poll is a tiny/204
  response; new messages appear within 4 s (or instantly with SSE) without losing scroll position or the text
  being typed in the box; pending/sent/failed/cancel states still update.
- **D5** Nothing lost: Telegram rules unchanged, every action in ui_inventory.json still reachable, full pytest +
  scripts/ui_check.py C1-C8 (en + my, phone + PC) + the 5.3 perf_check numbers stay green or improve (record the
  chat-open time before/after in REPORT.md).

## Loop
M0 measure chat-open (bytes, ms, DOM nodes) before -> build A -> build B -> run pytest + ui_check + perf_check +
Playwright flows (open a 600-message chat, scroll up 3 times, receive a new message while scrolled up and while
at the bottom, send a reply, cancel within the undo window, open #m-old link) -> list failures -> fix the biggest ->
run again until D1-D5 are true. Do not lower the goal, skip, delete or xfail tests. One line per loop in
REPORT.md "5.7 scoreboard". Restart the web service in the same step as each deploy. Stop only for something the
owner must decide.

## OWNER TEST 5.7 (PC)
1. Orders: click Today / Yesterday / 7 days / 30 days / All time — the list and the tab numbers change; each row
   shows its date. Pick dates… 1 Nov – 5 Nov. Press Back — the previous range returns. Same chips on Payments.
2. Open a customer with a long chat (your second account): it opens fast and shows the latest messages at the
   bottom. Scroll to the top — older messages load above and the screen does not jump. Keep going to the very
   first message ("Beginning of the conversation").
3. Send a message from the customer account while you are at the bottom: it appears by itself. Scroll up and send
   another: a "New message ↓" pill appears; click it.
4. Type half a reply and wait 10 seconds: your text stays; the chat does not flicker.
