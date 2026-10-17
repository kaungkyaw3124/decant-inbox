# Epic 4.12 — AI address assistant + AI payment-screenshot reader (owner decision 2026-10-17)

Live test 2026-10-17 23:27: Order #1001 was approved and the confirmation said
`လိပ်စာ: လိပ်စာ ပြောင်းချင်ပါတယ်` (left-over damage from the 4.8 bug), and the KBZPay screenshot
showed 70,000 Ks paid to "Soe Htike Lwin" while the order total was 34,000 — nothing warned.
Owner: "the address should be supervised by AI." Same "How to work" loop as docs/SPEC-v4.md
(tests -> fix -> green -> self-review -> deploy -> report), plus real-API eval gates below.
Commit + push after EACH part (N0, N1, ...) with its tests green.

## Privacy switches (/ai, owner only)
- `ai_address` (default ON): addresses are sent to OpenAI for understanding (they were masked
  until now). Phones stay masked as [PHONE]; customer names never sent.
- `ai_screenshot` (default OFF): payment screenshots are sent to OpenAI to read. Owner turns it
  on after reading the note on /ai: "screenshots contain names and account numbers".
- Both: store=false, same caps/budget, errors -> fallback to the manual flow (never block work).

## N0 — Data repair + guard (no AI needed)
- One-off script: find orders/customers whose saved address is not a valid address by the new
  validator (N1 rules, e.g. "လိပ်စာ ပြောင်းချင်ပါတယ်", text shorter than 8 chars, only keywords).
  Print them (ids only), do NOT change automatically; mark them `address_invalid=true` so the
  dashboard shows a red badge and the owner can fix them ("Edit locked order" for paid ones).
- From now on an address is saved ONLY through the validator (N1). The old free-text path is removed.

## N1 — AI address assistant
- When: a customer message that may contain an address (rules address/change_info, or the AI
  says intent address, or we are waiting for an address) -> extract with the AI (if ai_address
  ON) else rules.
- AI output (strict schema, in the existing understand() call where possible to avoid a 2nd
  call): address {house_no, street, ward_or_quarter, township, city, landmark, full_text,
  missing: [fields], is_change_request: bool, confidence}. full_text = the clean address only,
  no phone, no ကိုပို့ပေးပါ etc., digits kept as written.
- Validator (our code, final say): valid if township OR (city + street) present and full_text
  is not just keywords/intents; township checked against a Myanmar township list
  (data/townships.csv: Burmese + English spellings, Yangon/Mandalay first; AI may propose a
  normalized township; we accept only names in the list or flag "unknown township").
- Outcomes:
  - valid + confidence >= 0.85 -> save structured + full_text on order AND customer; continue the
    flow (ask phone / payment info / address_updated line as today).
  - missing township (or city) -> auto ask (templates): `ဘယ်မြို့နယ်လဲ ပြောပေးပါနော်။`
    (ask_township) / `ဘယ်မြို့လဲ ပြောပေးပါနော်။` (ask_city); merge the answer with the
    partial address (keep partial for 24 h).
  - message is a change request without an address -> 4.8 ask_new_address (AI or rules).
  - unsure / invalid -> Needs you card "📍 check address" with the AI's split shown, editable.
- Dashboard: cart/order panel shows the structured address (township bold), ✅ valid / ⚠️ reason.
## N2 — Address gates (money safety)
Blocked while the order address is missing or invalid (red reason shown, owner/staff can fix it
in the panel with the same validator):
- sending payment info (manual or auto)
- approving a payment
- sending the order confirmation
The order confirmation always shows the structured address (full_text).
## N3 — AI payment-screenshot reader (only if ai_screenshot ON)
- S0 capability check: one test call with a sample image (tests/fixtures/payment_screens/*,
  synthetic images Claude Code generates — no real customer data) to confirm the configured
  model reads images. If not supported -> report on /ai "screenshot reading not available with
  model X" and keep N3 off; everything else still ships.
- When a single payment photo arrives for an order (existing payment check), and the switch is
  ON: send the image + expected total + active payment methods (name, number last 4) to the AI.
  Output: {app (KBZPay/AYA Pay/Wave/other), amount, currency, transaction_no, time,
  receiver_name, receiver_account_last4, status_text ("Payment Successful"…), is_payment_receipt,
  confidence}.
- Checks (our code) -> warnings on the payment card (and in Needs you):
  - not a payment receipt / unreadable
  - amount != order total (show both; "paid more" and "paid less" distinguished)
  - receiver name/number does not match any active payment method (fuzzy name, last-4 digits)
  - transaction_no already used on another approved check (exact match)
  - receipt time earlier than the order's payment-info time, or older than 3 days
  - status text not success
- Pre-fill the card: amount, transaction_no (admin still must type/confirm the ID from the
  KPay/AYA app — keep the existing required field; pre-filled value marked "from screenshot"),
  method. Approve with any warning needs the existing second confirm.
- Never auto-approve. Never message the customer automatically about these warnings (the admin
  uses the existing reject reasons).
## N4 — /ai and Settings
- /ai: switches ai_address / ai_screenshot with privacy notes; counts (addresses read, asked
  township, invalid caught; screenshots read, warnings by type); cost.
- Settings: templates ask_township, ask_city, address_invalid_note.

## Acceptance tests (fake AI provider in pytest; loop until 100% green)
P1 live data case: an order whose address is "လိပ်စာ ပြောင်းချင်ပါတယ်" -> N0 marks invalid; payment
   info, approve and confirmation are all blocked with the reason; fixing the address unblocks.
P2 "ဒီကိုပို့ပေးပါ ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅ ဖုန်း 09777123456" -> address full_text without phone and
   without ကိုပို့ပေးပါ, township ဗဟန်း, phone saved separately, payment info next.
P3 "သုခလမ်း အမှတ် ၁၂" (no township) -> ask_township; reply "ရန်ကင်း" -> merged, valid, continue.
P4 keyword-only / change request messages never become an address (4.8 regression).
P5 unknown township -> Needs you check-address card; admin fixes -> continues.
P6 ai_address OFF -> rules path still works; nothing address-like is sent to the provider
   (payload test).
P7 screenshot (fake AI result) amount 70,000 vs total 34,000 -> "paid more" warning; receiver
   "Soe Htike Lwin" not matching "Test Shop" -> receiver warning; approve requires 2nd confirm;
   nothing auto-approved; nothing sent to the customer.
P8 duplicate transaction_no from the screenshot -> warning; old receipt (before payment info) ->
   warning; not a receipt -> warning.
P9 ai_screenshot OFF -> no image is ever sent (payload test); card works as before.
P10 regression: all earlier tests, 4.10 matrix, fixtures.
## Real-API eval gates (scripts/ai_eval.py extensions)
- Address set (>= 30 cases, Burmese/English/mixed, Zawgyi, Burmese digits, with phones,
  partial addresses, change requests, keyword-only): township correct >= 95%, full_text never
  contains a phone, 0 keyword-only messages accepted as an address. Loop prompt -> re-run.
- Screenshot set (if the model supports images): >= 8 synthetic receipts (KBZPay/AYA/Wave-like,
  correct/wrong amount, wrong receiver, not-a-receipt): amount exact >= 95%, transaction_no exact
  >= 90%, is_payment_receipt correct 100%. If it can't reach that, keep N3 OFF and report.
Deploy: backup, migrations, ai_address ON, ai_screenshot OFF, restart, health. Then OWNER TEST
SCRIPT 4.12 in REPORT.md (incl. fixing Order #1001's address with "Edit locked order", and how
to turn on screenshot reading and test it with the owner's KBZPay test screenshot).
