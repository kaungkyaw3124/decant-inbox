# v3 Implementation plan: after-payment flow, safety nets, FAQ, sales

Agreed with the owner 2026-10-15 in the planning chat. Builds on docs/SPEC-orders.md
(Steps 1-5 done). Do the steps IN ORDER, one at a time.

## How to work (applies to every step)
1. `git pull --rebase`. Read this file, docs/SPEC-orders.md and the latest REPORT.md entry.
2. Implement the step.
3. Write the step's ACCEPTANCE TESTS (listed below) as automated pytest scenarios using the
   fake Telegram client (same style as tests/test_cart.py / test_auto.py / test_payments.py):
   customer messages in -> exact replies out, DB state checked.
4. Run the FULL suite (`.venv/bin/pytest -q`). If anything fails: find the cause, fix the
   code (not the test, unless the test is wrong about the spec), and run again.
   Repeat until everything passes. Never skip or delete a failing test to get green.
5. Apply migrations live only after a fresh backup; round-trip (down/up) every migration.
6. Restart services, check `/healthz` and `bash scripts/status.sh`.
7. Commit + push, write a REPORT.md entry (what, decisions, test results), update PLAN.md
   "RESUME HERE", then go on to the next step without waiting, unless blocked by something
   only the owner can do (then stop and say exactly what is needed).
8. After the LAST step, write "OWNER TEST SCRIPT" in REPORT.md: the exact messages to send
   from a second Telegram account and what should happen after each one.
Rules that stay: the system suggests, admin decides for money; auto only when certain;
Telegram send rules in CLAUDE.md; all templates editable in Settings; mobile-first.

---------------------------------------------------------------------------------------
## Step 6 — After payment + safety nets
### 6.1 Delivery statuses
- Order flow after Paid: `paid -> packed -> sent_out -> delivered` (+ cancelled).
- Orders page (/orders): tabs "To pack" (paid), "To send" (packed), "Sent" (sent_out),
  "Delivered", "All"; each row: Order #, customer, items, total, phones, address, age.
  Buttons: 📦 Packed, 🚚 Sent out, ✅ Delivered (each one tap, 60 s undo, audit_log).
- Sent out: optional fields deli name / deli phone / note. Auto message (template
  `order_sent_out`): `Order #{order_no} ကို ပို့လိုက်ပါပြီ။{deli_line}\nပို့ခကို ပစ္စည်းရောက်မှ ပေးချေပေးပါနော်။`
  where deli_line = `\nDeli: {deli_name} {deli_phone}` only when given.
- Delivered: no message by default (setting "Send thank-you on delivered" off; template
  `order_delivered` = `ပစ္စည်းရရှိပြီဖြစ်လို့ ကျေးဇူးတင်ပါတယ်။ နောက်လည်း အားပေးပါဦးနော်။`).
- Auto-delivered: sent_out older than N days (setting, default 5) -> delivered (no message).
- Customer asks about delivery (`ဘယ်တော့ရောက်မလဲ`, `ရောက်ပြီလား`, `deli`, `ပို့ပြီးပြီလား`) while
  they have a paid/packed/sent_out order -> new intent `ask_delivery` -> auto reply by status:
  paid/packed: `Order #{order_no} ကို ပြင်ဆင်နေပါတယ်။ ပို့လိုက်တာနဲ့ အကြောင်းကြားပေးပါမယ်နော်။`
  sent_out: `Order #{order_no} ကို {sent_date} မှာ ပို့ပြီးပါပြီ။{deli_line}`
### 6.2 Payment reminder + auto-cancel
- Order in waiting_payment with no photo: after `reminder_hours` (default 12) send ONE
  reminder (template `payment_reminder`):
  `Order အတွက် ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။ စုစုပေါင်း {total} ကျပ်ပါ။`
  After `cancel_hours` (default 48) -> cancelled + template `order_auto_cancelled`:
  `ငွေလွှဲမှု မရရှိသေးတဲ့အတွက် အော်ဒါကို cancel လုပ်ထားပါတယ်။ ပြန်မှာချင်ရင် ပြောပေးပါနော်။`
  + shown in Needs you as info. Both hours in Settings; auto-reply OFF => no reminder/cancel
  messages (only listed in Needs you). Never more than one reminder per order. Respect
  owner pause / never-auto customers.
### 6.3 Unanswered messages go to Needs you
- ANY incoming customer message that got no reply (auto or human) within 2 minutes AND the
  customer has an open cart or an order not yet delivered -> "🟡 Needs you: unanswered".
  Cleared when we reply (any way) or the admin marks it done/ignored.
- Also any `other`/`unknown` message from a customer who wrote in the last 7 days.
### 6.4 Cancel the whole order
- `cancel`, `မယူတော့ဘူး`, `မမှာတော့ဘူး`, `အော်ဒါ cancel` WITHOUT a product name = intent
  `cancel_order`.
  - Open cart / confirmed / waiting_payment (no photo yet) -> auto: cancel + template
    `order_cancelled`: `အော်ဒါ cancel လုပ်ပြီးပါပြီ။ နောက်မှ ပြန်မှာချင်ရင် ပြောပေးပါနော်။`
  - photo_received / paid / later -> NO auto; Needs you ("customer wants to cancel a paid
    order") -> admin decides (refund outside the system; button "Cancel order" + note).
  - With a product name it stays `remove` (existing behaviour).
### 6.5 Wanted but not stocked
- /reports/wanted: list from unknown_requests (not_stocked) + out-of-stock asks: name,
  times asked, last asked, customers count. Sort by times asked.
### Acceptance tests (Step 6)
A1 paid order -> Packed -> Sent out with deli -> customer gets exact order_sent_out text with
   deli line; without deli -> no deli line. Delivered -> no message (setting off) / thank-you
   (setting on). Sent out 5 days -> auto delivered.
A2 "ဘယ်တော့ရောက်မလဲ" while paid -> preparing text; while sent_out -> sent text with date.
   Same message with no order -> NOT ask_delivery auto reply (goes to Needs you).
A3 waiting_payment 12 h (fake clock) -> exactly one reminder; 48 h -> cancelled + message;
   photo arrives at 13 h -> no cancel. Auto OFF -> no messages, listed in Needs you.
A4 customer with open cart sends "authentic လား" -> no auto reply -> after 2 min in Needs you
   unanswered; admin custom reply -> cleared.
A5 "မယူတော့ဘူး" (no product) with open cart -> cancelled + message; with a paid order ->
   no auto, Needs you. "swy မယူတော့ဘူး" -> remove item (unchanged behaviour).
A6 wanted report counts two customers asking the same unknown name.

---------------------------------------------------------------------------------------
## Step 7 — FAQ auto-answers
- Settings > FAQ: list of entries {keywords (comma separated, Burmese/English, normalized),
  answer text, active}. Seed (owner edits later):
  1. deli time: `ဘယ်နှစ်ရက်, ဘယ်လောက်ကြာ, delivery time, ရောက်ဖို့` -> `ရန်ကုန်မြို့တွင်း ၁-၂ ရက်၊ နယ်ကို ၃-၅ ရက်လောက် ကြာပါတယ်နော်။`
  2. authentic: `authentic, original, စစ်လား, အစစ်လား, tester` -> `အားလုံး authentic (original) ပစ္စည်းတွေ ကနေ ခွဲထည့်ပေးတာပါနော်။`
  3. payment: `ဘယ်လိုပေးရ, ငွေဘယ်လိုလွှဲ, cod, kpay ရလား` -> `KPay / AYA Pay နဲ့ ကြိုလွှဲပေးရပါတယ်။ ပို့ခကိုတော့ ပစ္စည်းရောက်မှ ပေးရပါတယ်နော်။`
  4. location: `ဘယ်မှာလဲ, ဆိုင်, location, လာယူ` -> `Online ကနေ ပို့ပေးတာပါနော်။`
  (Use these as seed text; mark them "edit me" in the UI.)
- Matching: on normalized text; FAQ only when the message has NO product/size/order intent
  (so "swy 5ml authentic လား" is handled as price + FAQ? -> keep simple: if a product is
  named, the normal flow wins and the FAQ match goes to Needs you as a hint).
  Several FAQ matches -> send the best one (most keywords), others ignored.
- Auto mode sends FAQ answers with the same speed/safety rules; auto OFF -> one-tap
  "💬 Send FAQ: {title}" button. Every FAQ send in the chat with 🤖.
- Unmatched questions -> Needs you (Step 6.3).
### Acceptance tests (Step 7)
B1 "authentic လား" -> FAQ 2 answer auto (auto ON) / one-tap button (auto OFF).
B2 "ဘယ်နှစ်ရက်ကြာလဲ" -> FAQ 1. B3 inactive entry not used. B4 "good girl 5ml ဘယ်လောက်လဲ"
   still gets the price reply (not FAQ). B5 editing keywords in Settings changes matching
   immediately. B6 unknown question -> nothing sent, Needs you.

---------------------------------------------------------------------------------------
## Step 8 — Daily sales & profit dashboard (backlog item the owner asked for)
- Cost prices: Excel gets optional columns `bottle_cost` (what the owner paid for the full
  bottle) — cost per ml = bottle_cost / full_size_ml; optional `vial_cost` setting per decant
  size (Settings, default 0). Cost history like prices (cost at time of sale is stored on
  order_items when the order is paid: unit_cost).
- Sales page (/sales): date range (today, yesterday, this week, this month, custom, Asia/Yangon
  days). Counts only PAID (and later) orders, by paid_at.
  Tiles: revenue, orders, items sold, ml sold, cost, profit, profit %, average order.
  Tables: per day; per perfume (qty, ml, revenue, cost, profit) sorted by revenue; per size.
  Simple bar chart per day (inline SVG, no external libs). Missing cost -> profit shown as
  "—" with a note "add bottle_cost in the price list".
- Export the selected range to .xlsx.
### Acceptance tests (Step 8)
C1 two paid orders on two days + one cancelled + one waiting -> only paid counted, per day
   correct (Yangon midnight boundary). C2 cost per ml math (bottle_cost 300000 / 100 ml, 5 ml
   decant, vial_cost 500 -> cost 15500). C3 price changed after sale -> report uses price at
   sale. C4 missing cost -> profit "—". C5 export has the same totals as the page.

---------------------------------------------------------------------------------------
## Step 9 (LATER, do not start without the owner) — Inventory in ml per bottle.
