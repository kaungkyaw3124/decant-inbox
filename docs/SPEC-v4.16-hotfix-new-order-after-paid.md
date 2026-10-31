# Epic 4.16 — Hotfix from live test 2026-10-31 09:46 (owner screenshot). Build NOW.
Same loop (tests -> fix -> green -> self-review -> deploy -> report). Commit after each part.

## Live chat (second account; Order #1003 is paid = locked)
- 09:46 customer, ONE message: "hi swy 10 ml ဝယ်ချင်လို့ပါ\n09958645521\n66 str 29 str, mandalay ကို ပို့ပေးပါ"
- 09:46 we: "Order #1003 ကတော့ အတည်ပြုပြီးသားပါ။ ဒါကို order အသစ်အနေနဲ့ ယူပေးပါမယ်နော်။ • Stronger With You 10ml –
  30,000 ... ဖုန်း 09958645523, 09945827742၊ လိပ်စာ no(121), 73, 45 လမ်း mandalay ကို ပို့ပေးရမလား။"
  **BUG 1:** the NEW phone and NEW address in the same message were ignored; the OLD saved ones were offered.
- 09:46 customer: the test code (tester account) -> 09:47 we: holding reply only.
  **BUG 3:** nothing told the tester why the code did nothing (payment info was not sent yet: the order was still
  waiting for "yes, deliver there").
- 09:48 customer: "လိပ်စာက 66 str, 28 str mandalay ပါ" -> we: "Order #1003 က ငွေရပြီး အတည်ပြုပြီးသားဖြစ်လို့ ပြင်ဆင်လို့
  မရတော့ပါဘူး..." **BUG 2:** the address was for the NEW cart, but we answered about the locked #1003.

Planning chat reading of app/orders/actions.py (confirm in Q0):
- BUG 1: the buy/cart_add path never applies `contact_in(message)` (phones + address read from the same message);
  cart_text then falls back to cart.customer_phones / cart.saved_address.
- BUG 2: the `_locked` branch fires when the open cart has no order.address / order.phones — but that cart only
  *shows* the saved ones (fallback), so it looks "empty" and the change goes to the locked order.

## Q0 Root cause
Find these 4 messages in the DB (parse results, auto_runs, ai_calls, outbox). Write in REPORT.md exactly why each
reply was chosen. Confirm or correct the reading above. Add a test reproducing each bug first (red), then fix.

## Q1 Same-message contact wins (all buy paths, locked or not)
- When a buy / order message (rules or AI, single or multi-item, new cart or existing cart) also contains a phone
  and/or an address, store them on the order (order.phones / order.address, same validation + cleaning + AI address
  check as the address step) BEFORE composing the reply. The reply shows the NEW phone/address.
- Several phones: the new one(s) from this message only; old saved phones are NOT added unless the customer asks.
- Address invalid/partial -> the normal "which township?" / ask-address flow for the NEW address; never fall back to
  the old saved address when the customer just gave a different one.
- Same rule for a phone-only or address-only message while a cart is open.
## Q2 New cart after a locked order receives the changes
- If the customer has an open cart/order (status cart/confirmed/waiting_payment) that is newer than the locked paid
  order, every address/phone/change_info/remove/modify message applies to that OPEN order. The locked-order reply
  (order_locked) is only for messages when there is NO open order, or that clearly name the locked order
  (its Order ID, or "the paid one / ငွေလွှဲပြီးသား order").
- Treat an open cart that shows fallback contact (saved phone/address) as having contact for this decision.
- Expected for 09:48: address of the NEW cart becomes "66 str, 28 str, mandalay" (Mandalay, grid 66 x 28), reply
  = the confirm question with the new address (or payment info if already confirmed).
## Q3 Mandalay grid with "str"
- "66 str 29 str", "66 str, 28 str", "66st x 28st", "၆၆ လမ်း ၂၈ လမ်း" -> grid street, city Mandalay = valid.
  Add to the 4.13 Q5 cases and the address eval set.
## Q4 Test code at the wrong step (testers only)
- Tester sends the code while the order is NOT yet waiting for payment: reply to that chat (tester only, never to
  others) with template test_code_too_early:
  `🧪 Test code ရပါတယ်၊ ဒါပေမဲ့ order ကို အရင် အတည်ပြုပေးပါ (ငွေလွှဲအချက်အလက် မပို့ရသေးပါ)။`
  If the order has items + phone + valid address and only waits for "yes": treat the code as "yes" + payment
  info sent + test payment in one go (so a tester can finish fast). No holding reply for code messages.
- Keep: a non-tester sending the code gets nothing special (4.14 rule).

## Tests
R1 the 09:46 message (rules path + AI path): new cart with SWY 10ml, phones = [09958645521] only, address
   "66 str 29 str, mandalay" (Mandalay); reply shows the new phone/address; locked_new_order first line kept.
R2 the 09:48 message after R1: applies to the new cart (address 66 x 28), never the order_locked reply;
   #1003 unchanged.
R3 with no open cart, "change my address" -> order_locked reply still (4.10 behaviour kept).
R4 message naming #1003 while a new cart is open -> order_locked reply for #1003.
R5 Mandalay "str" grid variants valid.
R6 tester code too early: confirm-ready order -> payment info + test check in one go; incomplete order ->
   test_code_too_early; non-tester -> nothing special; no holding reply for the code.
R7 regression: full suite + 4.10 matrix + fixtures + ui gate quick mode.
Eval: add the 09:46 and 09:48 messages + 5 "str" grid addresses to the address set; gate unchanged.
Deploy + OWNER TEST 4.16 (resend the 09:46 and 09:48 messages from the second account, then the test code).
