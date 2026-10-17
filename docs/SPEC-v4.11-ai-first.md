# Epic 4.11 — AI-first inbox (REPLACES docs/SPEC-v4.11-live-fixes.md; owner decision 2026-10-17)

Owner: "I don't want to teach. OpenAI should handle new wording. The web app asks the admin
only when it really can't decide." Build AFTER 4.10. The old 4.11 file is superseded; its K1
(form expired) and K4 (stale Needs you) are kept below as L6/L7.

## Target workflow
Customer message
 1. Patterns (seed rules + approved learned patterns): certain -> auto reply (unchanged).
 2. Not certain -> OpenAI (AI mode AUTO):
    a. confident (>= threshold, default 0.85) + checker OK -> auto action + reply (🧠),
       learning in the background (L4).
    b. 2-3 candidate products for one item -> ask the CUSTOMER a numbered choice (L3).
    c. a perfume we don't sell, confident -> not-stocked line (existing).
    d. unsure / error / budget or cap / real question -> admin (Needs you) with a SIMPLE card (L5).
 3. Admin card: AI answer pre-selected, ✅ to send, or change. No teaching words, no learn box.
Never automatic (unchanged): payment approval, sending answers to real questions, changes to
locked paid orders (4.10), anything on ignored / never-auto customers.

## L1 — Switch to AUTO now, keep the brake
- Migration/data step: set AI mode = AUTO, auto-graduate OFF (we skip the shadow period by
  owner decision). Keep the safety brake from 4.7 (wrong product on an AUTO message, accuracy
  < 90% on last 30, errors >= 50% of last 20 -> back to SHADOW + notice). Keep "🧠 AI was wrong".
- /ai shows a banner "AUTO since <date> (owner skipped shadow); brake ON".

## L2 — Several actions in one message (live case)
"Y edp မယူတော့ဘူး ဗျ liquid brun 10 ml ယူပါမယ်" with Y EDP 10ml in the cart.
- AI schema: items[].action add | remove | ask_price (+ existing fields). Message intent
  "modify_cart" when it mixes adds and removes. Checker: remove only for products in the cart
  (else drop that item and lower confidence); add/ask_price as before.
- Rules: clause split on ဗျ / နော် / ပြီးတော့ / , / ။ / and action words; if every clause is
  certain, rules handle it without the AI.
- Apply all actions together and send ONE reply, in this order: removed lines
  (`{product} ကို ဖြုတ်လိုက်ပါပြီ။`, template item_removed), not-stocked lines, then the current
  list + total, or if the cart is now empty `ခြင်းထဲမှာ ဘာမှ မကျန်တော့ပါဘူး။ တခြား ဘာယူချင်လဲ။`
  (template cart_empty), then the next step / resume line; if waiting_payment and the total
  changed -> payment info again (4.10 rule). Paid orders: locked (4.10).
## L3 — Ask the customer to choose (instead of the admin)
- When the AI (or rules) give 2-3 candidate products for an item (e.g. "ysl 10ml" -> Y EDP or
  Libre), auto-send (template choose_product):
  `{text} ထဲက ဘယ်ဟာလဲ –\n1. {p1}\n2. {p2}\nနံပါတ်လေး ပြောပေးပါနော်။` and store a choice_prompts row
  (reuse 4.3) with the pending action (add/ask_price/remove, size, qty). Reply "1"/"၁"/name ->
  continue the original action automatically. Expires 24 h. Other replies -> normal parsing.
- More than 3 candidates or none -> admin (L5).
## L4 — Automatic learning (no admin teaching)
- When the AI resolves the SAME normalized text to the SAME meaning 3 times (different messages,
  no correction in between) -> the pattern becomes APPROVED automatically (actor "🧠 auto-learn").
  Owner can still remove it on Learning. Learned from a corrected result: never.
- Nickname and intent-phrase proposals follow the old K3 rule: short reusable phrases only
  (product names, <= 4-word intent phrases, no numbers/sizes/particles, never whole sentences,
  never already-known phrases).
- Learning page: "auto-learned" section with counts; owner "remove" stays.
## L5 — Simple admin card
- Needs-you card (owner + staff) = the AI's understanding pre-selected per item (product, size,
  qty, action) + the reply preview; buttons ✅ ပို့မယ် / ✏️ ပြင်မယ် / 🙅 ဘာမှမလုပ်နဲ့.
- No "teach" words, no learn checkbox (learning is L4). One row per item with its own action
  (L2). Questions: AI draft in an editable box (unchanged, never automatic).
- Practice mode and the staff guide are updated to the new card.
## L6 — "Form expired" keeps the admin's work (old K1)
On CSRF mismatch for a normal POST: redirect 303 back to the same safe internal page with a flash
"ဒီစာမျက်နှာ သက်တမ်းကုန်သွားလို့ ပြန်ဖွင့်ပေးထားပါတယ်။ ထပ်နှိပ်ပေးပါ။" and the card selections restored;
htmx -> HX-Refresh. Never act on a mismatched token.
## L7 — Stale items in Needs you (old K4)
Items > 24 h whose customer wrote again since -> collapsed "Older (n)" with "Dismiss all older"
(undo 60 s). Payments never move to Older. Badge counts current items only.

## Acceptance tests (loop until 100% green; fake AI provider in pytest)
M1 live case (AUTO): remove Y EDP + liquid brun not sold -> ONE reply: removed line + not-stocked
   line + cart_empty text; cart empty; ai_calls decision auto.
M2 remove + add known in one message -> one reply with removed line + new list + total; in
   waiting_payment -> also payment info again with the new total.
M3 "ysl 10ml ယူမယ်" -> AI candidates [Y EDP, Libre] -> choose_product sent; reply "၂" -> Libre 10ml
   added + list; expired prompt (25 h) -> "2" not a choice.
M4 low confidence / error / cap -> Needs you simple card with AI answer pre-selected; ✅ sends the
   previewed reply; no learn box in the HTML.
M5 auto-learn: same text resolved identically 3 times -> approved, 4th message: no AI call;
   with a correction in between -> not approved; whole sentence never proposed.
M6 brake still works in AUTO (wrong product correction -> SHADOW + notice).
M7 form-expired redirect keeps selections, no DB change, no outbox row.
M8 Older section, dismiss all + undo, payments never older.
M9 real API: scripts/ai_eval.py extended with >= 10 new multi-action / candidate cases (incl. the
   live sentence); gate: intent+products >= 90%, 0 wrong product ids, remove only for cart items.
M10 regression: all earlier tests, fixtures, 4.10 matrix.
Deploy: backup, migration, AI mode AUTO, brake ON, restart, health. Then OWNER TEST SCRIPT 4.11
(second account): the live sentence, "ysl 10ml ယူမယ်" -> choose 2, a question -> draft card,
3x the same new nickname -> auto-learned, form-expired check, Older section.
