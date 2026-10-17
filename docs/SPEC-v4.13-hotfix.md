# Epic 4.13 — Hotfix from live test 2026-10-18 02:04 (owner screenshot). Build NOW.
Same "How to work" loop (tests -> fix -> green -> self-review -> deploy -> report). Commit after each part.

Live chat (second account, Order #1001 paid):
- 01:59 "hi decant မှာချင်လို့ပါ" -> NO reply.
- 02:01 "hello?" -> "Order #1001 ကို ပြင်ဆင်နေပါတယ်။ ဘာများ ထပ်ကူညီပေးရမလဲ။" (ok)
- 02:02 "swy intensely 10ml ထပ်ယူပါမယ်ဗျ" -> locked_new_order + list + ask address (ok)
- 02:04 "no(121) ,73, 45 လမ်း mandalay ကို ပို့ပေးပါဗျဖုန်းနံပါတ်က 09945827742" -> NO reply for 6+ min.
Planning chat reproduced with app/orders/address.py:
- clean() keeps "ကို ပို့ပေးပါဗျဖုန်းနံပါတ်က" in full_text (space before ပို့ပေးပါ; glued particles ဗျ / က).
- validate("hi decant မှာချင်လို့ပါ") -> status "partial", missing township (no place words at all!).

## Q0 Root cause first
Find the 02:04 message in the DB (customer of the test account): parse result, ai_calls row (decision,
error, result), auto_runs, Needs-you entry. Write in REPORT.md exactly why no reply was sent. Fix that
cause; add a test that reproduces it.
## Q1 Never leave a customer in silence
- While a customer has an open cart/order (not delivered) OR the message is a buy/price request, every
  incoming text message must result within 60 s in: an auto reply, OR a queued one-tap/admin action
  plus a HOLDING reply (template holding_reply):
  `ခဏစောင့်ပေးပါနော်၊ စစ်ပြီး ပြန်ပြောပေးပါမယ်။`
  at most once per 10 minutes per customer, never when a person replied by hand in the last 10 min,
  never for ignored / never-auto customers. Needs you marks these items "⏰ customer waiting" (top).
- Add a watchdog in the worker: any such message older than 60 s with no outgoing reply/holding
  reply/queued action -> send holding reply + Needs you (and log "silent message caught").
## Q2 "Want to order" without a product
- New intent order_start (seed: မှာချင်, မှာချင်လို့ပါ, ဝယ်ချင်လို့, order တင်ချင်, အော်ဒါတင်ချင်, want to
  order, can I order) when no product/size is present -> auto reply (template ask_what_product):
  `ဘယ်ပစ္စည်း မှာချင်လဲ ပြောပေးပါနော်။` (greeting prefix by the 6 h rule; combined with 4.9 smart greeting
  when it also contains hi/hello). AI may also return it.
## Q3 Address cleaning
- clean()/strip: remove request words with or without spaces and glued particles: ကို ပို့ပေးပါ,
  ကိုပို့ပေးပါ, ပို့ပေးပါ, ပို့ပါ, ကိုပို့, + trailing particles ဗျ, ဗျာ, နော်, ရှင့်, ရှင်, ခင်ဗျာ, ပါ, က;
  phone lead-ins ဖုန်းနံပါတ်က / ဖုန်းက / ph / phone / tel with or without spaces/colons; the phone.
- Expected: "no(121) ,73, 45 လမ်း mandalay ကို ပို့ပေးပါဗျဖုန်းနံပါတ်က 09945827742" ->
  full_text "no(121), 73, 45 လမ်း, mandalay" (spacing may differ, but NO request words, NO particles,
  NO phone), city Mandalay, phone 09945827742 added (no change words -> add, 4b rule).
## Q4 Validator: no place words = not an address
- "partial" requires at least one place element (house no, street/လမ်း/road/st, ward/ရပ်ကွက်/quarter,
  township, city, landmark word). Greetings / order wishes / product requests -> "invalid: no address"
  (never ask township for them).
## Q5 Mandalay-style addresses
- Accept grid streets: "73 x 45", "73x45", "၇၃ လမ်း x ၄၅ လမ်း", "73, 45 လမ်း", "between 73 & 74",
  "၇၃ နဲ့ ၇၄ ကြား", "၇၃ လမ်း (၄၅ x ၄၆ ကြား)". City Mandalay + grid street = valid.
- data/townships.csv must include Mandalay townships (Chanayethazan ချမ်းအေးသာစံ, Mahaaungmye
  မဟာအောင်မြေ, Aungmyethazan အောင်မြေသာစံ, Chanmyathazi ချမ်းမြသာစည်, Pyigyitagon ပြည်ကြီးတံခွန်,
  Amarapura အမရပူရ, Patheingyi ပုသိမ်ကြီး) — add if missing.
## Tests (+ real-API eval additions)
R1 the live 02:04 message (rules path and AI path): clean full_text, Mandalay, phone added, payment
   info / next step sent within 60 s (or holding reply if the AI is unsure) — never silence.
R2 "hi decant မှာချင်လို့ပါ" -> greeting + ask_what_product; validate() -> invalid (not partial).
R3 watchdog: simulated stuck message -> holding reply once, Needs you "⏰", not twice in 10 min.
R4 cleaning cases: 12 variants of request words/particles/phone lead-ins.
R5 Mandalay grid formats (8 variants) valid; Mandalay townships recognized.
R6 regression: all earlier tests + 4.10 matrix + fixtures.
Eval: add the live sentences + 10 Mandalay/grid addresses to the address set; gate unchanged
(township/city correct >= 95%, 0 phones in full_text, 0 keyword-only/greeting accepted).
Deploy + short OWNER TEST (resend the two live messages from the second account).
