# v5.8.1 HOTFIX — send the FINAL summary (items, total, phone, address) together with the payment info
Live case 2026-11-10 00:32 (owner screenshots, order #1005):
1. Bot asked the returning customer: "ဖုန်း 09111111111၊ လိပ်စာ No. 12, Example St ကိုပဲ ပို့ပေးရမလား။"
2. Customer: "ဖုန်းနံပါတ်ချိန်းချင်ပါတယ် 09222222222" (I want to change the phone number: new number).
3. Bot saved the new phone and at once sent ONLY: items + total + KPay/AYA lines + "send the screenshot".
   The customer never saw the updated phone / address, so he could not check them before paying. (The paid order
   then showed phone 09222222222 and address "No. 12, Example St" — right, but he paid without seeing it. Next he
   asked to change the address; the order was already paid and locked.)
Owner's rule: **after a change of phone or address we send ONE message with ALL the final information + the
online-payment accounts + "if the information is correct, send the transfer screenshot".**
Same loop as 4.20 (simulator + tests -> fix -> green). Small epic: do it, test it, deploy it, report it.

## The message (templates stay editable in the Replies page; Burmese wording below is the default)
When payment info is sent (first time) or sent again because something changed, the reply is, in this order:
1. (only after a change) the confirmation line: `ဖုန်းနံပါတ် ပြင်ပြီးပါပြီ – {phone}` / `လိပ်စာ ပြင်ပြီးပါပြီ – {address}`
   (existing templates phone_updated / address_updated; both lines if both changed)
2. the item lines + total (cart_line, payment_total as now)
3. NEW `payment_summary_phone`:   `ဖုန်း: {phones}`
4. NEW `payment_summary_address`: `လိပ်စာ: {address}`
5. the payment-method lines (KPay / AYA … as now)
6. footer (template payment_info_footer, new default text):
   `အချက်အလက်အားလုံး မှန်ရင် ငွေလွှဲပြီး transaction id ပါတဲ့ screenshot လေး ပို့ပေးပါနော်။ ပြင်စရာရှိရင် အခု ပြောပေးပါ။`
   (the short resume_payment / ask_screenshot reminders keep their own text)
Example (the live case, after the fix):
```
ဖုန်းနံပါတ် ပြင်ပြီးပါပြီ – 09222222222
• Ultra Male 10ml – 28,000 ကျပ်
စုစုပေါင်း 28,000 ကျပ်ပါ။
ဖုန်း: 09222222222
လိပ်စာ: No. 12, Example St
KPay – … / AYA Pay – …
အချက်အလက်အားလုံး မှန်ရင် ငွေလွှဲပြီး transaction id ပါတဲ့ screenshot လေး ပို့ပေးပါနော်။ ပြင်စရာရှိရင် အခု ပြောပေးပါ။
```

## Rules
- **Every route that sends payment info uses the same builder** (cart.payment_text and its callers: normal
  confirm / "yes" / returning-customer agreement, change_info by rules, change_info by the AI, new phone/address
  answers, "total changed" resend, test code path). Find all callers (grep payment_text, payment_info_sent,
  "payment_info") — no route may build its own shorter text.
- **Phone and address lines are always included** in that message (all saved phones of the order, max 3, the
  order's address). If the phone or address is still missing, nothing changes: the bot asks for it first
  (existing gates) and does not send payment info.
- **Change while we wait for the payment (status waiting_payment, no screenshot yet):** the old 4.8 rule "do not
  resend, only the confirmation line" is CHANGED: send the full message above again (confirmation line + summary +
  accounts + footer). Rate limit / dedupe: never twice for the same change; two quick changes in one customer burst
  (quiet window) = one message with the latest values.
- **Change before payment info was sent (cart / confirmed):** save, then the full message above (as the live case).
- **Unchanged and locked:** photo_received / paid / packed / sent_out / delivered keep the 4.10 locked-order rules
  (hold reply + Needs you); nothing in this fix touches them.
- AI path: when the AI returns change_info (+ the new value) the same builder is used; the AI never writes the
  summary text itself (privacy rules and templates stay as they are).
- Test shop payment lines stay whatever is configured; do not change data.

## Tests (must fail before the fix)
1. Returning customer says yes → one message with items, total, phone, address, accounts, footer.
2. The live case: cart + returning-customer question, "ဖုန်းနံပါတ်ချိန်းချင်ပါတယ် 09222222222" → exact message
   above (new phone, old address).
3. Same with address change ("လိပ်စာ ပြောင်းချင်ပါတယ် 12 Bahan") and with both in one message.
4. Payment info already sent, then a phone change → full message again (not just the confirmation line); a second
   identical message does not send it twice.
5. Rules route AND AI route (fake AI client returns change_info) give the same text.
6. Missing address → still asks the address, no payment info. Locked order → unchanged behaviour.
7. Replies page: the two new templates are listed, editable, previewed; footer default changed; existing custom
   edits of payment_info_footer are kept (migration/seed must not overwrite an edited template).
8. Simulator: add these as scenarios (judge 0 wrong / 0 silent); live replay of the 2026-11-10 00:32 conversation
   (messages 1-3 above) produces the new message; full pytest + simulator quick run + ui_check green.

## OWNER TEST 5.8.1 (second Telegram account)
1. Order "Ultra Male 10ml" → bot lists the cart and asks "ဖုန်း …၊ လိပ်စာ … ကိုပဲ ပို့ပေးရမလား။".
2. Reply "ဖုန်းနံပါတ်ချိန်းချင်ပါတယ် 09222222222" → ONE message: phone changed line, item, total, phone, address,
   KPay/AYA, "if everything is correct, send the screenshot".
3. Reply "လိပ်စာ ပြောင်းချင်ပါတယ် No. 34, Sample Rd, Mandalay" BEFORE paying → the full message again with the new address.
4. Pay with the test code → order paid. Try to change the address now → polite "order confirmed, we'll check"
   message (unchanged).
