# Epic 4.17 — Hotfix 2 from live test 2026-10-31 10:27: more automatic, never silent. Build after 4.16.
Same loop (tests -> fix -> green -> self-review -> deploy -> report). Commit after each part.

## Live chat (second account; Order #1003 paid; an unconfirmed cart from 09:46 has "Stronger With You 10ml")
10:27 customer, ONE message: "Swy intensely 20ml ယူပါမယ်\n66 str 28 str ကိုပို့ပေးပါ\n09958745521"
Result: **no reply at all for 5+ minutes** (not even the holding reply). Needs you got a one-tap card
("❓ str str") whose draft:
- adds "Stronger With You Intensely 20ml" (20ml is NOT on the price list: 2/5/10 ml only) AND
  "Stronger With You Intensely 2ml" — **the 2ml was invented from the address** ("28 str");
- uses the OLD phones / address (4.16 Q1 fixes that);
- says "20ml ကိုတော့ စစ်ပြီး ပြန်ပြောပေးပါမယ်" and waits for a person.
Also: the earlier test code message (09:46) sits in Needs you as a 🧠 AI card → check TEST_PAY_CODE /
is_tester for that account (owner may not have set them yet) and report which.

## P0 Root cause (REPORT.md)
For the 10:27 message: parse results (rules + AI), ai_calls (what the AI returned), auto_runs decision and why it
did not auto-send, and **why the 4.13 holding reply / watchdog did not fire**. Fix each cause; tests first (red).

## P1 Never silent (again, stronger)
- The 4.13 rule must hold for EVERY incoming text when a one-tap card / Needs you item is created or the message
  is left unanswered: holding reply within 60 s (once per 10 min per customer, not after a manual reply in the
  last 10 min, not for ignored / never-auto customers, never for the tester's test code). Add a test with
  exactly the 10:27 message and the conditions of that chat (open cart + locked paid order + earlier holding
  reply 40 min ago).
## P2 Address text is never a product or a size
- Before product/size matching (rules AND the AI checker), find the address and phone parts of the message
  (address reader + phone regex). Numbers and words inside them (66, 28, str, st, street, လမ်း, x, house no,
  phone digits) can never create an item or a size. "28 str" must never become "2ml".
- AI checker: drop an item whose evidence text is only inside the address/phone span; the AI prompt says so too.
- Line-based: a line that is an address (validator says partial/valid) is not parsed for products.
## P3 Size not sold → automatic answer (no person needed)
- Known product + size not on the price list (e.g. 20ml) → auto reply (template size_not_available):
  `{product} က {size} မရှိပါဘူးနော်။ ရနိုင်တဲ့ size တွေ: {sizes_with_prices}။ ဘယ် size ယူမလဲ?`
  sizes_with_prices = "2ml – 8,000 / 5ml – 18,000 / 10ml – 33,000 ကျပ်" (only in-stock sizes). Remember the
  question; the answer "10ml" / "၁၀" / "10" / "ဒုတိယ" adds that size to the cart (then the normal next step).
- Other sellable items in the same message are added normally; the reply combines both (one message).
- Same for "full bottle" when no full-bottle price exists.
- Never invent a price; an unknown PRODUCT still goes to the AI / person as today.
## P4 Phone + address in the same buy message (with 4.16 Q1)
- The 10:27 message must end as: cart = old 10ml line kept + SWY Intensely (size question), phone 09958745521,
  address "66 str 28 str" Mandalay (grid 66 x 28). Reply = one message: size question + "ဖုန်း 09958745521၊
  လိပ်စာ 66 x 28 လမ်း, Mandalay ကို ပို့ပေးရမလား" after the size is chosen (or in the same message if the
  owner prefers: keep it ONE question at a time — size first).
## P5 Old unconfirmed cart
- If a cart is older than 30 min and the customer starts a new buy message, the reply's list shows ALL items
  (as now) with a short line: `အရင်က ရွေးထားတာလည်း ပါပါတယ်၊ မလိုရင် ဖျက်ပေးပါ့မယ်။` so the customer can remove
  it ("10ml မယူတော့ဘူး" already works via 4.11).

## Tests
S1 the exact 10:27 message (rules path + AI path): no 2ml item, size question with 2/5/10 prices, phone
   09958745521, address 66 x 28 Mandalay, ONE auto reply within 5 s; no Needs you card.
S2 answer "10ml" → SWY Intensely 10ml added, then the confirm question with the NEW phone/address.
S3 address/phone digits never become items: 12 variants ("28 str", "no 12", "၆၆ လမ်း", "73x45", phones).
S4 holding reply fires for any message that still goes to a person (P1 conditions incl. the 10:27 setup).
S5 full bottle with no price → size question; unknown product → AI/person as before.
S6 old cart line shown (P5).
S7 regression: full suite + 4.10 matrix + fixtures + ui gate quick mode + address eval.
Deploy + OWNER TEST 4.17: resend the 10:27 message from the second account; answer "10ml"; then "ok"; then
the test code (after marking the account 🧪 and setting TEST_PAY_CODE).
