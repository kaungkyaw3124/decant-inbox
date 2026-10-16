# Epic 4.8 — Changing address / phone (live bug 2026-10-17)

LIVE BUG: returning customer got "ဖုန်း …၊ လိပ်စာ … ကိုပဲ ပို့ပေးရမလား။", answered
"လိပ်စာ ပြောင်းချင်ပါတယ်" (I want to change the address). The word လိပ်စာ made it
intent=address -> counted as agreement -> payment info sent with the OLD address.
Same "How to work" loop as docs/SPEC-v4.md (tests -> fix -> green -> self-review -> deploy
-> report). Fix first, then add the feature.

## Rules
1. An `address` intent needs real address CONTENT (street/number/ward/township/landmark text
   beyond keywords). Keywords alone ("လိပ်စာ", "ပို့ပေးပါ", "address") are NOT an address and
   NEVER count as agreement.
2. New intent `change_info` (subtypes: address | phone | both | unclear), seed phrases:
   လိပ်စာပြောင်း, လိပ်စာ ပြောင်းချင်, လိပ်စာအသစ်, လိပ်စာ မှားနေ, တခြားလိပ်စာ, ဒီလိပ်စာ မဟုတ်ဘူး,
   ဖုန်းပြောင်း, ဖုန်းနံပါတ်ပြောင်း, ဖုန်းအသစ်, change address, new address, change phone,
   wrong address. Learnable (4.2 card + 4.6 AI may return change_info).
3. Negative answer to the returning-customer question ("…ကိုပဲ ပို့ပေးရမလား။"):
   မဟုတ်ဘူး / no / မဟုတ်ပါ / ပြောင်းမယ် -> treated as change_info(unclear).
4. Replies (templates, editable):
   - change_info address: `ပို့ပေးရမယ့် လိပ်စာအသစ် ပို့ပေးပါနော်။`  (template ask_new_address)
   - change_info phone:   `ဖုန်းနံပါတ်အသစ် ပို့ပေးပါနော်။`          (ask_new_phone)
   - unclear/both:        `လိပ်စာအသစ်နဲ့ ဖုန်းနံပါတ် ပို့ပေးပါနော်။` (ask_new_contact)
   The order goes to state "waiting new address/phone": payment info is NOT sent until the new
   info arrives (if it was already sent, nothing is resent yet).
5. "Replace" vs "add":
   - After change_info(address) or with words like "ဒီလိပ်စာကိုပို့ပေးပါ <address>" / "ဒီကိုပို့ပါ" /
     "this address": the new address REPLACES the order's address AND the customer's saved address.
   - After change_info(phone): the new number becomes phone 1 of the ORDER (old order phones
     removed); on the customer it becomes phone 1 (old ones kept below, max 3).
   - A new phone without change words = add (current behaviour).
6. What happens next, by order status:
   - cart / confirmed / waiting_payment (no photo): save -> reply
     `လိပ်စာ ပြင်ပြီးပါပြီ – {address}` (or phone) and continue the flow: if payment info was
     NOT sent yet -> send it; if it WAS sent -> do not resend (amount unchanged), only the
     confirmation line. (Template address_updated / phone_updated.)
   - (OVERRIDDEN by 4.10: paid orders are locked; photo_received -> Needs you, no auto change)
   - photo_received / paid / packed: save on the order + reply the confirmation line + Needs you
     notice "📍 Order #N address changed after payment — check before packing/sending".
   - sent_out / delivered: do NOT change automatically -> Needs you ("customer wants to change
     the address of an order already sent"), no auto reply.
7. The payment-info message and the final confirmation always use the CURRENT order address/phone.
8. Dashboard: the cart/order panel shows "address changed at hh:mm (old: …)" for 24 h; order
   page keeps history of address/phone changes (order_events).

## Acceptance tests
H1 the live bug: returning customer, cart list with returning ending -> "လိပ်စာ ပြောင်းချင်ပါတယ်"
   -> reply ask_new_address, NO payment info, order waiting new address; then
   "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅" -> address replaced (order + customer) -> address_updated line +
   payment info with the NEW address.
H2 "ဒီလိပ်စာကိုပို့ပေးပါ - လှိုင် ပြည်လမ်း ၁၀" as the answer to the returning question -> replace +
   payment info with the new address (no ask).
H3 keyword only: "လိပ်စာ" / "ပို့ပေးပါ" alone -> not address, not agreement, no payment info.
H4 "မဟုတ်ဘူး" to the returning question -> ask_new_contact; then phone + address in one message
   -> both replaced -> payment info.
H5 change after payment info sent (waiting_payment) -> address_updated line only, payment info
   NOT resent; the later Order confirmation shows the new address.
H6 change after paid -> saved + reply + Needs you notice; after sent_out -> no auto change,
   Needs you.
H7 "ဖုန်းပြောင်းချင်တယ်" then "09444555666" -> order phones = [09444555666]; customer phone 1 =
   09444555666, old kept as phone 2. A plain new number without change words still ADDS.
H8 regression: all fixtures + all previous tests pass; rules certain -> no AI call.
