# Epic 4.6 — AI helper (OpenAI) with an evaluation gate

Agreed with the owner 2026-10-16. Provider: OpenAI API (Myanmar is a supported country).
Model: `gpt-6-luna` (cheapest: $0.10 in / $0.01 cached in / $0.50 out per 1M tokens).
The owner put `OPENAI_API_KEY` in `.env` himself. NEVER print, log or commit the key.

Principle: the AI only UNDERSTANDS messages for the web app. It never talks to customers,
never writes customer replies (except DRAFTS for questions, which a human must send), never
invents products. Replies keep coming from our templates and prices. The AI plugs into the
existing v4 learning system: what the AI understood becomes PENDING learned patterns.

Work exactly like docs/SPEC-v4.md "How to work" (tests, loop until green, self-review vs the
goal, backup, deploy, report, PLAN.md). Steps in order:

---------------------------------------------------------------------------------------
## S0 — Key check (stop if it fails)
- Read OPENAI_API_KEY from .env (pydantic settings, SecretStr). One tiny call to gpt-6-luna.
  Report only OK / the error type (auth, billing/no credit, country, network). If it fails,
  STOP and tell the owner what to fix (e.g. "add credit in Billing").

## S1 — AI client + checker (no effect on customers yet)
- app/ai/: provider interface `understand(message, context) -> AIResult`;
  implementations `openai` (official SDK, current API; check the SDK docs for structured
  JSON output with a strict JSON schema) and `fake` (tests). Setting AI_PROVIDER
  (openai|off), AI_MODEL (default gpt-6-luna), AI_REASONING (default low).
- Request: static part FIRST (instructions + product list with ids, names, nicknames, sizes
  sold, FAQ titles) so prompt caching works; then the dynamic part: the message, last 10
  messages of the chat, cart, last paid order items (names only).
- PRIVACY: before sending, replace phone numbers with [PHONE], addresses/long numbers with
  [ADDRESS]/[NUMBER]; never send photos, payment info, names of customers. Ask the provider
  NOT to store the request (store=false) where the API supports it.
- Output schema (strict): intent (the app's intents incl. previous_item, greeting,
  question, address, other), items[{product_id|null, size (2/5/10ml|full|null), qty,
  not_in_list|null, unclear_text|null}], learn[{text, kind: nickname|intent_phrase|
  not_stocked, product_id|null, intent|null}], confidence 0-1, reason (short English),
  draft_answer (only for intent=question; Burmese; may be null).
- CHECKER (our code): product ids exist and are active; sizes are sold; qty 1-20;
  no product id for not_in_list items; learn entries refer to text that really occurs in
  the message; JSON valid. Any failure -> result rejected (logged), treated as "AI unsure".
- Timeouts 8 s, 1 retry on network errors only; cost per call computed from usage tokens
  (prices in settings) and stored: ai_calls(message_id, model, input/cached/output tokens,
  cost_usd, latency_ms, ok, error, result_json, decision).
- Daily cap (setting, default 300 calls) and monthly budget (default $5): over the limit ->
  no call, message goes to Needs you as today.

## S2 — EVALUATION GATE (run before anything is visible to staff)
- tests/fixtures/ai_eval.csv: at least 40 cases with expected intent / product / size /
  qty / not_in_list, including the owner's real examples:
  "ysl edp 10 ml ရောယူပါမယ်"(buy,Y EDP,10) · "hawas for him 10ml ယူမယ်"(buy, null,
  not_in_list) · "Good girl 5ml, swy 10ml, liquid brun 10ml ယူပါမယ်"(3 items, 3rd
  not_in_list) · "ဟိုနေ့ကဟာ ၂ခု ထပ်ယူမယ်" with context last order Good Girl 5ml
  (previous_item/buy, Good Girl 5ml qty 2) · "ဒီအနံ့က ဘယ်လိုမျိုးလဲ ညနေဘက်သုံးလို့ရလား"(question)
  · "stonger with u intense 5ml ဈေးဘယ်လောက်လဲ"(ask_price, SWY Intensely, 5) · "ysl ကို မယူတော့ဘူး"
  with cart Sauvage 5ml + Y EDP 5ml (remove Y EDP) · "ရန်ကင်း သုခလမ်း အမှတ်၁၂ ကိုပို့ပေးပါ ဖုန်း
  ၀၉၇၇၇၁၂၃၄၅၆"(address) · "hi ဘာတွေရလဲ"(greeting/question) · "ဘလူးဒီချန်နယ် အပြည့်ဗူး ရှိလား"
  (ask_stock, BDC, full) — plus the fixture rows that rules can't handle and typos/Zawgyi.
- scripts/ai_eval.py runs the set against the REAL API (cost ~ a few cents), prints per case
  ✅/❌, accuracy by field, cost, average latency; saves a report under data/exports/.
- PASS criteria: intent+products correct >= 90%; ZERO wrong product ids (a wrong product is
  worse than null); not_in_list cases never mapped to a product. If it fails: improve the
  instructions/examples in the prompt (not the expected answers), try AI_REASONING=medium,
  re-run. Loop. If still failing after reasonable effort, STOP and report numbers to the
  owner. Record final numbers in REPORT.md.
- pytest uses the fake provider (no network) for all logic tests.

## S3 — Shadow mode in the product
- Where: parser worker, AFTER rules. Call the AI only when rules are not certain (fuzzy,
  partial, unknown text, intent other/unknown, previous_item without history match) AND the
  message is not handled by an approved learned pattern. Never for photos, payments.
- AI mode setting (owner): OFF / SHADOW (default after deploy) / AUTO.
- SHADOW: the AI result fills the teaching card (4.2) — answers pre-selected, "🧠 AI
  suggests" label + the reason; the admin just checks and taps ✅ (or changes). Accepted
  unchanged -> ai_calls.decision=accepted; changed -> corrected. Learned patterns from the
  card are created as before (pending, taught_by "AI + <user>").
- intent=question: card shows the AI draft_answer in an editable box -> admin sends or edits.
  Questions are NEVER sent automatically, in any mode.
- not_in_list with confidence >= 0.85: card pre-selects "🚫 ဒီပစ္စည်း မရှိဘူး".

## S4 — AUTO mode (owner switches it on after shadow results look good)
- AUTO: if checker passes AND confidence >= threshold (setting, default 0.85) AND intent is
  one of buy/ask_price/ask_stock/remove/cancel_order(open cart only)/confirm/address/
  greeting/ask_delivery/previous_item(resolved by history) AND every item has a product_id or
  is not_in_list with confidence >= 0.9 -> save parse result method="ai" and let the existing
  auto engine continue (same safety rules: quiet window, delay, owner pause, caps).
  Below threshold -> SHADOW behaviour.
- Patterns learned from AI results stay PENDING; they become approved by the owner or by 3
  accepted/uncorrected uses (existing rule). Approved patterns make the next message free.
- Chat shows 🧠 on AI-understood messages (hover: reason).

## S5 — AI page (owner)
- /ai: mode switch, today / this month: calls, cost USD, average latency, accepted vs
  corrected (accuracy %), messages handled by learned patterns (calls saved); last 50 calls
  with result + decision; daily cap / monthly budget / threshold / model / reasoning settings;
  "Run evaluation" button (runs scripts/ai_eval.py, shows the latest report).
- Needs you shows a notice when: API error rate high, credit/budget exhausted, cap reached.

## Acceptance tests (fake provider unless stated)
F1 checker rejects: unknown product id, size not sold, not_in_list with product id, learn text
   not in message, invalid JSON -> message goes to Needs you, nothing sent.
F2 privacy: phone/address/long digits are masked in the request payload.
F3 cap/budget reached -> no call, Needs you; next day counter resets.
F4 timeout / network error / 401 / 429 / insufficient quota -> no crash, Needs you, notice.
F5 SHADOW: "ysl edp 10 ml ရောယူပါမယ်" -> card pre-filled with Y EDP 10ml + 🧠 reason; accept
   -> list sent; patterns pending; ai_calls.decision accepted.
F6 AUTO: same message, confidence 0.93 -> auto list sent (🧠), patterns pending; confidence
   0.6 -> shadow card instead.
F7 "hawas for him 10ml ယူမယ်" AI not_in_list 0.95 -> AUTO: not-stocked reply; SHADOW: card
   pre-selects မရှိဘူး.
F8 question -> never auto-sent; draft shown; admin sends.
F9 rules-certain messages never call the AI (call count 0).
F10 approved learned pattern -> next same message handled by rules, no AI call.
F11 cost accounting: tokens -> cost matches the price settings.
F12 (REAL API, scripts/ai_eval.py) passes the S2 criteria; numbers in REPORT.md.

## Owner test script (write in REPORT.md at the end)
Shadow first: send the 10 example messages from a second account; for each, what the card
shows and what to tap. Then switch AUTO and repeat 3 of them. Then show the AI page numbers.
