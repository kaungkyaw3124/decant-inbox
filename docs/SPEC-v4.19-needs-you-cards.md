# Epic 4.19 — "Needs you" redesign: one customer = one clear card. Build after 4.17.
Owner feedback 2026-10-31 11:01 (screenshot of the Inbox): "the UI is bad, I don't even know where to look or
what to do." The same customer appeared 3 times (customer waiting + locked-order note + AI card), technical
labels ("❓ str str", "(88%)"), no single obvious action, and a draft that contradicted itself.
Approved mockup: docs/mockups/needs-you-phone.dc.html (390 px phone). Match its layout and wording; use the
v4.15 Bootstrap base, app.css tokens and the Burmese font. Same loop (tests -> fix -> green -> ui_check ->
look at screenshots -> deploy -> report).

## Hard limits
- No behaviour change in what gets sent or decided (4.16/4.17 do that). Same routes, POST actions, CSRF, HTMX,
  permissions. Existing tests: update only markup selectors (list them in REPORT.md); the 4.15 C7 inventory may
  change ONLY where this spec merges/removes duplicate controls — update ui_inventory.json with a note per change.

## N1 One card per customer
- needs_you() groups every open item by customer: waiting/holding, AI or one-tap card, locked-order note,
  payment/test-code notes, learning item tied to that message. ONE card per customer, sorted by how long the
  customer has waited (oldest first). Items with no customer (e.g. AI key refused, service down) are a separate
  "⚙️ System" card at the top, red.
- The card's main item = the newest message that needs an answer. Other items of that customer fold into
  "N older notes" (expand inline). Old items whose message was answered later (a reply was sent after it) are
  auto-done, not shown.
## N2 Card content (exact order, as the mockup)
1. Header: avatar initials, name, a short context line (New order · city / Order #T3 paid / Asking price …),
   and a red "waiting N min" pill (amber under 2 min, red from 2 min).
2. The customer's message(s) as a chat bubble (keep line breaks), and a small line "time · got 'please wait' at
   …" when a holding reply was sent.
3. "WHAT THE BOT UNDERSTOOD": a short list, ✓ green for understood facts (product, size, qty, phone, address,
   payment), ⚠ amber for the ONE thing that needs a person, in plain words (e.g. "20ml is not on your price
   list", "Can't tell which product", "Address has no township"). No confidence %, no raw tokens like "str str",
   no intent names. Owner can see details (AI %, parse) behind a small "Details" toggle.
4. "REPLY THAT WILL BE SENT": the exact text as an outgoing bubble. If there is no safe reply, say "No reply
   ready — open the chat" and show only the Open chat button.
5. Buttons: ONE big primary "Send this reply" (≥ 52 px); secondary "Edit reply" (inline editor, then Send) and
   "Open chat"; a small "Done (no reply)" link. Dangerous/rare actions go into the chat page, not the card.
6. A finished card disappears with a toast "Sent to Min Htet · Undo" (10 s), using the existing undo.
## N3 Top of the Inbox
- One status line: red "N customers waiting" (or green "All answered ✓"), plus 3 small chips: Payments n,
  To pack n, Learning n. Remove the 4 big tiles.
- The bottom tab bar Inbox count = customers waiting (not items).
## N4 Words
- English and Burmese texts for every new label (i18n_my.py), short and plain. Staff (Burmese) test:
  every label understandable without technical words.
## N5 Laptop
- Same cards in a centred column (max 720 px), or two columns from 1200 px (cards left, opened chat right).

## Tests
- K1 the 10:54 situation (open cart + locked #1003 + holding sent + AI card + older locked note) -> exactly ONE
  card for Min Htet, older notes folded, waiting pill, ⚠ line in plain words, no "str str"/"%".
- K2 two customers -> two cards, oldest waiting first; system problem card on top.
- K3 Send this reply -> same outbox row/undo as the old one-tap button; card gone; Undo brings it back.
- K4 Edit reply -> edited text sent; learning/human-correction behaviour unchanged.
- K5 no safe reply -> only Open chat; Done (no reply) marks done.
- K6 staff vs owner: staff sees the same cards; owner-only details hidden for staff.
- K7 ui_check full gate 0 fails (360/768/1280, en/my, owner/staff); look at the screenshots.
- K8 regression: full suite.

## OWNER TEST 4.19 (phone)
Send from the second account: one normal order message and one strange message. Inbox shows "1 customer
waiting" and ONE card per customer; you know in 3 seconds what to press. Press Send this reply -> the customer
gets it; Undo works. Switch to Burmese and repeat.
