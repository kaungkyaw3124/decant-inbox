# Epic 4.14 — Test payment code ("cheat code" for testing). Build NOW.
Same "How to work" loop (tests -> fix -> green -> self-review -> back up DB before migration -> deploy ->
report). Commit after each part.

## Why
While developing, the owner tests full orders from his second Telegram account. At the payment step he
does not want to send real money or real screenshots. Instead he types a secret code (like a game cheat
code); the system treats it as "payment screenshot received" for a TEST payment. Everything after that
(admin approve, Order ID, confirmation, packed / sent out / delivered) runs exactly like a real order.

## Safety rules (must all hold; a real customer must never get a free order)
1. The code is a secret: `.env` TEST_PAY_CODE (digits/letters, at least 8 chars). Empty or missing = the
   feature is OFF. Never in git, logs, templates, AI prompts or the dashboard (the settings page shows
   only "set" / "not set"). Add `TEST_PAY_CODE=` (empty) to .env.example.
2. It works ONLY from **test chats**: a new owner-only setting on /settings (or /auto): "Test accounts"
   = list of customers marked `is_tester`. Owner marks/unmarks a customer from the chat page
   ("🧪 Test account" toggle, owner only, audited). Staff cannot see or change it.
3. From a non-test chat the code is an ordinary message: no special reply, no hint, normal parsing. Write
   an AuditLog "test_code.non_tester" (customer id only, never the code) and show it on /ai or Needs you
   as "⚠️ someone sent the test payment code" so the owner can change the code.
4. Exact match after trim (case-sensitive, Burmese digits ၀-၉ converted to 0-9 first). The code message is
   never sent to the AI and never learned as a pattern.

## T1 Data (one Alembic migration)
- customers.is_tester bool default false.
- orders.is_test bool default false; payment_checks.is_test bool default false.
- Separate test order numbers: sequence `test_order_no_seq` starting at 1, shown as **T1, T2, ...**
  (real #1001+ numbering is never used by tests). Put the display logic in one helper
  (order_label(order) -> "#1001" or "T1") and use it everywhere the Order ID is shown or sent.

## T2 Recognise the code (parser worker, next to payments.scan)
- Customer is_tester AND has an order in waiting_payment (payment info sent) AND an incoming text equals
  TEST_PAY_CODE -> create PaymentCheck(decision="pending", is_test=true, message_id=that message),
  order.status = "photo_received", order.is_test = true. Same reply as for a real screenshot (the
  "received, checking" message, if one exists) so the customer flow is tested exactly.
- Code sent by a tester when no order is waiting for payment -> reply nothing special; Needs you note
  "🧪 test code but no order waiting for payment".
- Never runs the AI screenshot reader for a test check.

## T3 Approving a test payment (/payments card)
- Card shows a big "🧪 TEST PAYMENT — no money" banner instead of the screenshot.
- No screenshot download needed; transaction ID is filled automatically as `TEST-<check id>`; amount
  warnings are skipped. Address gate (4.12 N2) still applies (we are testing it too).
- Approve gives the next T-number, status paid, normal confirmation message (with "T3" as Order ID).
- Setting (owner-only) "Auto-approve test payments" default OFF. ON = the worker approves a test check
  by itself 5 s after it is created (user = system), so the owner can test the whole flow alone.
  Never applies to non-test checks (test: a real check with the setting ON stays pending).
- Reject works as usual (to test the reject messages).

## T4 Test orders stay out of the numbers
- /sales, daily/weekly reports, AI weekly summary, profit, Wanted report, future inventory (v5): exclude
  is_test orders. Orders list: test orders show a 🧪 badge and a filter "Show test orders" (default off).
- Owner-only button on /orders: "🗑 Clear test orders" (confirm twice) -> cancels all is_test orders that
  are not delivered and hides them; nothing is deleted from the database (messages are kept forever).

## Tests
- C1 tester + waiting_payment + exact code -> test check, photo_received, is_test, same reply as photo.
- C2 non-tester sends the code -> normal message, no check, audit "test_code.non_tester", warning shown.
- C3 TEST_PAY_CODE empty -> feature off for everyone (tester included).
- C4 wrong code / code inside a longer sentence / different case -> not recognised.
- C5 Burmese digits version of the code -> recognised.
- C6 approve test check: no screenshot needed, TEST-<id>, T-number, real sequence unchanged.
- C7 auto-approve ON: test check approved after 5 s; real check never auto-approved.
- C8 /sales and reports exclude test orders; "Clear test orders" cancels only test, undelivered.
- C9 code never appears in logs, AuditLog details, AI calls, templates or HTML (grep test).
- C10 staff cannot toggle tester, see the auto-approve setting, or clear test orders.
- C11 regression: full suite green.

## Owner test 4.14 (write it in REPORT.md)
1. Put your code in .env on the server: `TEST_PAY_CODE=<your secret>`; restart parser + web.
2. Chat page of your second account -> "🧪 Test account" ON.
3. From the second account: order -> phone -> address -> payment info arrives -> send your code.
4. /payments shows the 🧪 TEST card -> Approve -> customer gets the confirmation with Order ID T1.
5. /sales does not change. Turn "Auto-approve test payments" ON and repeat: confirmation within ~10 s.
6. From any other account the code does nothing special, and you see the ⚠️ warning.
