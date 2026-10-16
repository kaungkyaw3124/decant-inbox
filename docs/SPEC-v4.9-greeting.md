# Epic 4.9 — Smart greeting (owner feedback 2026-10-17)

Live case: customer has an order waiting for payment (payment info sent 01:47), sends "hi" at
02:31 -> no reply (greeting rule: only if we haven't messaged in 6 h). Owner: the customer
must get an answer. Same "How to work" loop as docs/SPEC-v4.md.

## Rules
1. A greeting-only message (intent greeting) gets an automatic reply unless we already sent a
   greeting reply to this customer in the last 30 minutes (setting greeting_repeat_minutes,
   default 30). The 6 h rule now only decides whether the reply STARTS with "မင်္ဂလာပါ။"
   (unchanged for other replies).
2. The greeting reply depends on the customer's current state (templates, editable):
   - no open cart/order: `မင်္ဂလာပါ။ ဘာကူညီပေးရမလဲ။`  (greeting_reply, unchanged)
   - open cart (not confirmed): greeting + current list + the normal closing question for the
     next missing step (phone / address / returning question).  (greeting_cart)
     `မင်္ဂလာပါ။ ခြင်းထဲမှာ ဒါတွေ ရှိပါတယ် –\n{items}\nစုစုပေါင်း {total} ကျပ်ပါ။\n{next_step}`
   - waiting for new address/phone (4.8): greeting + the same ask_new_* question.
   - waiting_payment: `မင်္ဂလာပါ။ {items_short} အတွက် စုစုပေါင်း {total} ကျပ် လွှဲပြီးရင် transaction id
     ပါတဲ့ screenshot ပို့ပေးပါနော်။ ဘာများ ထပ်ကူညီပေးရမလဲ။`  (greeting_waiting_payment)
   - photo_received: `မင်္ဂလာပါ။ ငွေလွှဲ screenshot ရပါပြီ၊ စစ်ပြီး အကြောင်းပြန်ပေးပါမယ်နော်။`
   - paid / packed: `မင်္ဂလာပါ။ Order #{order_no} ကို ပြင်ဆင်နေပါတယ်။ ဘာများ ထပ်ကူညီပေးရမလဲ။`
   - sent_out: `မင်္ဂလာပါ။ Order #{order_no} ကို {sent_date} မှာ ပို့ပြီးပါပြီ။ ဘာများ ထပ်ကူညီပေးရမလဲ။`
   (Never a "မင်္ဂလာပါ။ မင်္ဂလာပါ။" double prefix.)
3. Greeting + something else ("hi swy 5ml ဘယ်လောက်လဲ") -> handled as the other intent
   (unchanged).
4. Within the 30 min window, a repeated "hi" gets no auto reply but appears in Needs you as
   unanswered after 2 min (existing rule) — the customer may be waiting for a person.
5. Auto-reply OFF -> one-tap button with the same text.
## Acceptance tests
I1 the live case: waiting_payment, payment info sent 44 min ago, "hi" -> greeting_waiting_payment
   with items and total, no double greeting.
I2 no order -> greeting_reply; second "hi" 10 min later -> no reply + Needs you after 2 min;
   "hi" 35 min later -> reply again.
I3 open cart without phone -> greeting_cart ending with the ask-phone line.
I4 paid / sent_out / photo_received -> the matching texts with Order # and date.
I5 waiting new address (4.8) -> ask_new_address again with greeting.
I6 "hi swy 5ml ဘယ်လောက်လဲ" -> price reply (unchanged). All earlier tests pass.
