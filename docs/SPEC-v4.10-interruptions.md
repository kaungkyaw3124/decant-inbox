# Epic 4.10 — Interruptions & locked paid orders (owner decision 2026-10-17)

Customers jump around (add items, change address, ask questions, say hi) while the shop is
waiting for something (phone, address, payment screenshot). Rule: HANDLE the interruption,
ADJUST the order if allowed, then BRING THEM BACK with a "resume line". Build AFTER 4.9.
Same "How to work" loop as docs/SPEC-v4.md.

## Owner rule: paid orders are LOCKED
Once a payment is approved and the Order ID exists (status paid, packed, sent_out, delivered):
- NO change to items, quantities, address or phone by the customer, automatically or by
  one-tap. (This OVERRIDES 4.8 rule 6 "photo_received/paid/packed: save on the order".)
- Customer asks to add items -> start a NEW cart/order with those items (normal flow); reply
  starts with `Order #{order_no} ကတော့ အတည်ပြုပြီးသားပါ။ ဒါကို order အသစ်အနေနဲ့ ယူပေးပါမယ်နော်။`
  then the new list + next step. (template locked_new_order)
- Customer asks to remove/change items, change address or phone -> reply
  `Order #{order_no} က ငွေလွှဲပြီး အတည်ပြုပြီးသားဖြစ်လို့ ပြင်ဆင်လို့ မရတော့ပါဘူးနော်။ အကူအညီလိုရင် ခဏစောင့်ပေးပါ၊ ပြန်ဆက်သွယ်ပေးပါမယ်။`
  (template order_locked) + Needs you "🔒 customer wants to change paid Order #N: <what>".
  Nothing is changed.
- Cancel after paid -> unchanged (Needs you, admin decides, refund outside the system).
- OWNER override only: the order page has "Edit locked order" (owner role only, audit_log,
  reason required) for real exceptions. Staff cannot.
- photo_received (screenshot sent, not yet approved) is NOT locked but money is involved:
  item/address changes are NOT applied automatically -> Needs you "items/address changed after
  the payment screenshot" with the requested change; admin applies or rejects; customer gets
  `စစ်ပြီး ပြန်ပြောပေးပါမယ်နော်။`.

## Resume line (bring them back)
- After any auto reply that handles an interruption while a step is pending, append the resume
  line of that step (templates, editable): need_phone -> ask_phone; need_address ->
  ask_address; waiting new info (4.8) -> ask_new_*; waiting_payment ->
  `ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။`; photo_received -> none.
- At most once every 10 minutes per customer (setting resume_line_minutes, default 10) and
  never when the reply itself already asks for that step.
- Admin replies (custom / AI draft) get the resume line as a pre-filled suggestion they can
  remove.

## Behaviour by state (before payment approval) — must all be covered by tests
waiting_payment (payment info sent, no photo):
- buy/add (known) -> add -> new list + `စုစုပေါင်း အသစ် {total} ကျပ်ပါ။` + payment info again
  (template cart_total_changed); order stays waiting_payment with the new total.
- buy with unknown item -> reply `စစ်ပြီး ပြန်ပြောပေးပါမယ်နော်။` + Needs you card; after resolve ->
  same as above.
- remove -> new list + new total + payment info again; last item removed -> cancel (existing).
- change address/phone -> 4.8 (confirmation line; payment info not resent) + no extra resume
  line if the confirmation already contains it.
- ask_price for another product -> price + `ဒီ order ထဲ ထည့်ပေးရမလား။` + resume line; a following
  "ok/ထည့်ပေး/ဟုတ်" adds it (as buy) -> new total + payment info.
- FAQ -> answer + resume line. Other question -> Needs you (AI draft + suggested resume line).
- greeting -> 4.9. "လွှဲပြီးပြီ"/"paid" without photo -> `transaction id ပါတဲ့ screenshot လေး ပို့ပေးပါနော်။`
- new full order message -> merged into the same open order (one open order per customer).
- screenshot whose amount (typed by admin) != CURRENT total -> payment card warning shows both
  old and new totals (existing amount warning + "total changed at hh:mm").
cart / need_phone / need_address: handle as today, then resume line for the pending step.

## Dashboard
- Chat header + cart panel: current step badge ("⏳ waiting payment · total changed 02:41",
  "🔒 Order #1004 locked").
- Orders page: 🔒 icon on paid orders; owner-only "Edit locked order" with reason.

## Tests (loop until green)
J1 STATE x INTENT matrix: states {browsing, cart, need_phone, need_address, waiting_new_info,
   waiting_payment, photo_received, paid, packed, sent_out, delivered} x intents {buy known,
   buy unknown, remove, cancel_order, ask_price, ask_stock, faq, question, greeting,
   address, phone, change_info, paid_no_photo, photo, previous_item, ask_delivery} — every
   cell has a defined expected outcome in a table in the test file; all cells tested.
J2 story (owner's case): order -> payment info -> "liquid brun လည်းယူမယ်" (known) -> new total +
   payment info -> "လိပ်စာ ပြောင်းချင်ပါတယ်" -> new address -> "hi" -> screenshot -> admin types old
   amount -> warning shows old/new totals -> reject wrong amount (asks remaining) -> second
   screenshot -> approve -> Order # -> "swy 5ml လည်းယူမယ်" -> locked_new_order + NEW cart ->
   "လိပ်စာပြောင်းချင်တယ်" (about the paid order) -> order_locked + Needs you, nothing changed.
J3 resume line at most once per 10 min; not added when the reply already asks for the step.
J4 photo_received + add item -> no change, Needs you, holding reply.
J5 owner "Edit locked order" works with reason + audit; staff gets 403.
J6 regression: all earlier tests + fixtures + AI eval unaffected (rules-certain -> no AI call).
At the end: OWNER TEST SCRIPT 4.9 + 4.10 in REPORT.md.
