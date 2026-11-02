# Epic 5.2 — Customer care: profiles, reorder list, feedback after delivery. Goal-driven loop.
Same loop; continue until the goal is met. Telegram hard rules stay: nothing is sent to a customer without
either an admin click or an open order step; no bulk/broadcast messages.

## GOAL
- **C1** Opening a customer shows who they are in 3 seconds: total spent, orders, favourite perfumes/sizes,
  last order, notes, tags (VIP, wholesale, problem).
- **C2** The owner can win repeat sales with one tap per customer, safely (no automatic marketing).
- **C3** After delivery the shop learns if the customer is happy, and problems reach the owner at once.

## P1 Customer profile (customer panel in 4.21 + a full page)
- Totals (paid orders only, test orders excluded), first/last order, average order, top 3 perfumes, usual size,
  city; owner/staff notes (timestamped); tags with colours; "VIP" automatic suggestion at ≥ 5 orders or
  ≥ 200,000 Ks (owner confirms).
- Customers page: search, filter by tag/city, sort by spent / last order; CSV export (owner only).
## P2 Reorder list (admin click only)
- List of customers whose last decant was 25-45 days ago (setting), with a suggested short message
  ("SWY Intensely 10ml ကုန်ခါနီးပြီလား? ထပ်ယူချင်ရင် ပြောပါနော်") editable; **one tap = one message** to that
  customer through the outbox (rate limits apply). Max 1 such message per customer per 30 days; never to
  customers marked "never auto-reply"/ignored/opted-out; "stop"/"မပို့နဲ့" from a customer sets opted-out.
## P3 Feedback after delivery (setting, default OFF)
- 2 days after "delivered": one message "ပစ္စည်း အဆင်ပြေရဲ့လား? 👍 / 👎 သို့မဟုတ် စာနဲ့ပြောပေးပါ" (template).
  👍/positive → thank-you; 👎/complaint words → holding reply + Needs you (complaint, top priority) + alert.
  Only for orders the customer actually received; once per order.
## Tests
totals exclude test/cancelled; VIP suggestion; reorder window + 30-day cap + opt-out; feedback once, positive vs
complaint paths; staff cannot export CSV; simulator scenarios for feedback answers; full suite + ui gate green.
## OWNER TEST 5.2
Open your second account's profile (totals, top perfume). Reorder list → send one → arrives. Turn on feedback,
mark a test order delivered, wait (or use the "send now" test button) → answer 👎 → Needs you + alert.
