# Feature spec: Replies, Cart, Payment check, Orders (v2)

Agreed with the owner on 2026-10-11/12 in the planning chat. Build in the steps at the
bottom, one at a time, report in REPORT.md after each.

## Principles
1. The system SUGGESTS, the admin DECIDES. Nothing is sent to a customer, added to a cart,
   or approved without an admin tap. No auto-replies in v2.
2. Every outgoing message is previewed and editable before sending.
3. Problems are red and block the next step (e.g. no "Send payment info" while an item has
   no price).
4. Inbox sorted by "needs you": payments to check > unknown products > new requests.
5. Mobile-first (owner works on the phone, switching to the KPay app and back).
6. Every admin action is logged (who, when, what).

## Telegram account rules (changes CLAUDE.md "read-only")
- The server may SEND text messages to a private chat ONLY as the result of an admin click
  in the dashboard. Never edit, delete, forward, pin, or mark-read. Never message a chat
  that has not messaged us first.
- Only ONE process may use the Telethon session: the listener. Sending goes through an
  `outbox` table that the listener polls (status queued -> sent | failed, with error).
  Rate limit: max 1 message / 3 s overall, max 20 / min. On FloodWait: wait, keep queued.
- Capture OUR outgoing messages too (sent from the dashboard AND from the owner's phone),
  stored with direction=out, so the conversation view is complete and the greeting rule works.
- Photos: store metadata only (message id, grouped_id, file size, mime). Download a photo
  ONLY when an admin opens it, into secrets/media/ (dir 700, git-ignored). Never auto-download.

## One-tap quick replies (owner request 2026-10-12)
- On the message page AND on each inbox row: when the parse is ready for a quick reply
  (ask_price/ask_stock, product known, size known or "all sizes", every price present),
  show a button "💬 Reply price" that queues the price reply in ONE tap (no editor).
  The button shows the exact text on hover/long-press (title/tooltip) and a one-line
  preview under it.
- Safety: one-tap replies wait 10 s in the outbox with an "Undo" toast/button; after
  10 s the listener sends it. (Principle 2 "preview before send" is relaxed only for
  these one-tap template replies; the editor stays available via "Edit before send".)
- Not shown (fall back to the chat editor) when: product/size unknown, a price is
  missing, confidence below NEEDS_REVIEW_BELOW, or an outbox reply to that customer is
  already queued in the last 60 s.
- After queueing, the message is marked "done" automatically (undo restores status).
- The same one-tap pattern will be used for later quick replies (out of stock, ask for
  address, payment info) when their data is complete.

## Price list (Excel import/export)
One row per perfume:

| brand | name | full_size_ml | full_price | 2ml | 5ml | 10ml | in_stock |

- Size columns are dynamic: any header like `3ml`, `15ml` adds that decant size.
- Empty cell = size not sold. in_stock: yes/no.
- Import: upload .xlsx -> PREVIEW (changed prices, new products, unknown/ambiguous names,
  invalid cells) -> Confirm. Nothing saved before Confirm.
- Prices keep history (effective_from), so we know what a customer was quoted.
- "Download current prices" exports the same format (includes products added in the dashboard).
- The Excel replaces products.csv as the main catalog source (aliases stay in the dashboard /
  aliases.csv).

## Parser v2 (rules-2)
- Multi-item: split on `,` `၊` `နဲ့` `+` `and` new line; each part -> product + size + qty.
- Full size: `full`, `full size`, `fullbottle`, `ဗူးလိုက်`, `အပြည့်`, or size == full_size_ml.
- New intents: `remove` (မယူတော့ဘူး, ဖြုတ်ပေး, မလိုတော့ဘူး, cancel),
  `confirm` (အဆင်ပြေတယ်, ok, ဟုတ်ကဲ့, ရပါတယ်, confirm),
  `done` (ဒါပဲ, ဒါပါပဲ, ဒီလောက်ပါပဲ, ဒါတွေပဲ), `address` (…ကိုပို့ပေးပါ, လိပ်စာ, township words).
- Phone: Myanmar numbers (09…, +959…, Burmese digits) -> saved on customer.
- Context: size without product -> use the customer's last mentioned product (24 h),
  shown as "(from previous message)" and editable.
- Unknown product text is kept as `unknown_text` for the unknown-product flow.

## Conversation view (main screen)
Laptop: chat thread (in + out, photos as thumbnails-on-demand) | cart panel.
Phone: two tabs (Chat / Cart). One highlighted NEXT-STEP button per conversation.

## Flow and quick replies (all editable templates in Settings)
Greeting: prefix `မင်္ဂလာပါ။` only if we have not messaged this customer in the last 6 h.

1. Price question (NO cart):
   - size known: `{product} {size} က {price} ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။`
   - full size: same with full bottle price.
   - no size: list all sizes: `{product}\n• 5ml – 18,000 ကျပ်\n• 10ml – 32,000 ကျပ်\n• Full 100ml – 280,000 ကျပ်`
   - multiple products: one line each.
2. Buy -> [Add to cart] -> cart list reply:
   `• {product} {size} – {price} ကျပ်` per item + `စုစုပေါင်း {total} ကျပ်ပါ။ အဆင်ပြေရင် confirm လုပ်ပေးပါနော်။`
3. Remove -> [Remove from cart] -> same cart list reply with the new total.
4. Confirm -> if address or phone missing: `ပို့ပေးရမယ့် လိပ်စာနဲ့ ဖုန်းနံပါတ် ပို့ပေးပါနော်။`
   Address/phone saved on the customer; next time offer "Same address as last time?".
5. [Send payment info] (only when cart confirmed + address + phone present + every item priced):
   item list + total + active payment methods + `ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။`
   (No Order ID yet. No delivery fee in totals.)
6. Out of stock: `{product} {size} လောလောဆယ် ကုန်နေပါတယ်နော်။`
7. Custom: free text.

## Payment methods (Settings)
List of methods: name (KPay, AYA Pay, ...), account number, account name, active.

## Payment check
- Customer sends ONE photo while their cart is "waiting payment" -> "Payments to check" (badge).
- Several photos at once (same grouped_id, or >1 photo within 60 s): do NOT queue, do NOT
  download. Show "Several photos" + quick reply:
  `transaction id ပါတဲ့ screenshot တစ်ပုံတည်း ပို့ပေးပါနော်။`
- Payment card: customer, items, expected total, screenshot (downloaded on open, tap to zoom),
  fields: transaction ID (REQUIRED, typed from the admin's own KPay/AYA history), amount
  received, method. Buttons:
  - ✅ Approve: requires a single screenshot + transaction ID. Warn (and require a second
    confirm) if: transaction ID already used, same image hash used before, amount != total.
    -> creates the Order ID (e.g. #1001, sequential), status Paid, then offers the
    confirmation message:
    `✅ Order #{id} အတည်ပြုပြီးပါပြီ။\n{items}\nစုစုပေါင်း {total} ကျပ် (ငွေရရှိပြီး)\nဖုန်း: {phone}\nလိပ်စာ: {address}\nပို့ခကို ပစ္စည်းရောက်မှ ပေးချေရပါမယ်။\nကျေးဇူးတင်ပါတယ်။`
  - ❌ Reject, reasons:
    not received -> `ငွေမဝင်သေးပါဘူး။ ပြန်စစ်ပေးပါနော်။`
    wrong screenshot -> `ပို့ပေးတဲ့ screenshot က ဒီအော်ဒါနဲ့ မကိုက်ညီပါဘူး။ transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။`
    wrong amount -> `ကျန်ငွေ {remaining} ကျပ် ထပ်လွှဲပေးပါနော်။` (partial)
    Cart goes back to "waiting payment".
  - 🚫 Not a payment: dismiss photo, nothing sent.
- No manual "mark paid" without a screenshot.
- "Open in Telegram" link: https://t.me/{username} if username, else tg://user?id={id}.

## Cart / order states
cart -> confirmed -> waiting_payment -> photo_received -> paid (Order ID) -> (later: delivered)
cancelled any time before paid. Cart idle 3 days -> abandoned. One open cart per customer.

## Unknown product flow
Yellow card: "Customer asked: '{text}' — not in your product list."
- "Did you mean": top fuzzy matches -> tap -> item fixed + text saved as learned alias.
- ✅ We have it: quick form pre-filled (brand, name, asked size price required, other sizes
  optional) -> product + price saved (source manual, included in Excel export) -> item priced.
- ❌ We don't have it: reply `ဒီ product လောလောဆယ် မရှိသေးပါဘူးနော်။`, saved as "wanted
  but not stocked" (for reports).
- Product known but size not sold: [Add {size} price] or [Offer available sizes].

## Data model additions (Alembic)
product_prices(product_id, size_ml NULL=full bottle, is_full_bottle, price_mmk, in_stock,
effective_from, created_by) · messages: direction(in|out), kind(text|photo|other),
grouped_id, media meta · outbox(customer_id, text, status, error, created_by, sent_message_id)
· customers: phone, address · payment_methods · reply_templates(key, text) ·
carts/orders(order_no NULL until paid, status, customer_id, totals, timestamps) ·
order_items(product_id, size_ml, qty, unit_price) · payment_checks(order_id, message_id,
image_hash, transaction_id UNIQUE, amount, method, decision, reason, decided_by, decided_at)
· unknown_requests(text, customer_id, resolution) · audit_log.

## Build steps (one at a time)
- Step 1: Price list: product_prices, Excel import (preview/confirm) + export, price shown on
  product pages. Settings: payment methods, reply templates (defaults above).
- Step 2: Messaging core: capture outgoing + photo metadata, outbox + listener sender with
  rate limit, conversation view, Custom reply + Price reply. Update CLAUDE.md hard rules.
- Step 3: Parser rules-2 (multi-item, full size, remove/confirm/done/address, phone, context)
  + fixture tests (extend tests/fixtures/synthetic_messages.csv).
- Step 4: Cart + quick replies (add/remove/list, address/phone, payment info).
- Step 5: Payment check + Order ID + confirmation message.
- Step 6: Unknown product flow + "wanted but not stocked" list.
