# Release v4 — "Learning Inbox" (the app learns from the admin; no external AI)

Agreed with the owner 2026-10-16 in the planning chat. Builds on v1-v3 (all done).
Why no AI: the Claude API / Gemini API are not available in Myanmar; v4 makes the app learn
from the people who use the dashboard. An AI helper can be plugged in later (epic 4.6).
Users: the OWNER and STAFF admins who are NOT technical. Everything a staff member sees must
be simple, in Burmese, with big buttons, a preview before anything happens, and Undo.

## How to work (loop engineering — same as SPEC-v3, mandatory)
For EACH epic, in order 4.1 -> 4.5:
1. `git pull --rebase`; read this file, CLAUDE.md, the latest REPORT.md entry.
2. Implement the epic.
3. Write its ACCEPTANCE TESTS (below) as automated pytest scenarios with the fake Telegram
   client: customer messages in -> exact replies out -> DB state checked; web tests for UI.
4. Run the FULL suite. Failing? Find the cause, fix the CODE (change a test only if the test
   contradicts this spec), run again. LOOP until 100% green. Never skip/delete/xfail a test to
   get green. Also re-run tests/fixtures/synthetic_messages.csv: no regression allowed.
5. Backup -> migration (round-trip down/up tested) -> restart -> /healthz + scripts/status.sh.
6. Self-review against the epic's GOAL: re-read the goal, check each acceptance item is
   covered by a test that would fail if the feature broke. Fix gaps, loop again.
7. Commit + push, REPORT.md entry (what, decisions, test counts), PLAN.md "RESUME HERE".
8. Continue to the next epic without waiting. Stop only if something needs the owner.
9. After 4.5: write "OWNER TEST SCRIPT v4" in REPORT.md (exact messages from a second Telegram
   account + exact dashboard clicks + expected result for each), and a short "STAFF TEST"
   (what a non-technical staff member does, in Burmese).
Rules that stay: suggests-vs-decides for money; auto only when certain; Telegram send rules
(CLAUDE.md); every template editable; mobile-first; audit_log for every action.

---------------------------------------------------------------------------------------
## 4.1 Bug fix: partial name matches
GOAL: a known nickname inside a longer unknown name never produces a wrong product.
Live bug: alias "hawas" -> Hawas Ice; customer wrote "hawas for him 10ml"; the reply listed
Hawas Ice 10ml AND "hawas him ... မရှိသေးပါဘူး".
- In an item segment, if an alias match has extra unknown Latin words directly attached
  (before/after, same segment, before the size), the item is NOT a match: match="partial",
  unknown_text = the whole name ("hawas for him"), candidate product kept as a suggestion.
- One item segment produces ONE item (never a product AND an unknown for the same words).
- partial = not certain: no auto/one-tap reply; goes to Needs you with a teaching card (4.2)
  whose first suggestion is the candidate product.
Acceptance:
A1 alias hawas->Hawas Ice: "hawas for him 10ml ယူမယ်" -> 1 item, unknown "hawas for him",
   candidate Hawas Ice, no reply sent, in Needs you.
A2 "hawas ice 10ml ယူမယ်" and "hawas 10ml ယူမယ်" -> exact Hawas Ice (unchanged).
A3 "good girl 5ml, hawas for him 10ml ယူမယ်" -> Good Girl exact + 1 partial item, nothing
   auto-sent (whole message waits), never a reply naming both.
A4 all fixture rows still pass.

---------------------------------------------------------------------------------------
## 4.2 Teaching cards (learn from the admin)
GOAL: any message the app can't handle is turned into 1-3 simple questions; the admin's
answers finish THIS customer's request and teach the app for next time.
### What can be learned (stored in `learned_patterns`)
- kind=`nickname`: text -> product (e.g. "ysl edp" -> Y Eau de Parfum)
- kind=`intent_phrase`: text -> intent (e.g. "ရောယူပါမယ်" / "လည်းယူမယ်" -> buy)
- kind=`not_stocked`: text -> "we don't sell it" (e.g. "liquid brun")
Fields: kind, text, normalized_text, product_id NULL, intent NULL, status
(pending|approved|rejected), taught_by (user), taught_at, approved_by/at, confirmed_uses,
corrections, source_message_id. Unique (kind, normalized_text) among non-rejected.
### Parser use
- approved patterns = exactly like seed aliases/keywords (auto allowed).
- pending patterns = used to UNDERSTAND (match="learned_pending") but NOT auto: they show a
  one-tap suggestion "📘 learned (waiting approval)". When an admin accepts such a suggestion
  unchanged -> confirmed_uses += 1; if changed -> corrections += 1.
- Becomes approved when the owner approves it OR confirmed_uses >= N (setting
  `auto_approve_after`, default 3, 0 = owner only) with corrections = 0.
- rejected patterns are ignored.
- Longest match first; patterns never override a seed alias of a DIFFERENT product (conflict
  -> card asks the owner).
### The teaching card (message page + Needs you), Burmese first
For one message, show only the questions needed, max 3, each with big buttons and the most
likely answer first:
Q-product (unknown/partial/fuzzy name): `"{text}" ဆိုတာ ဘယ်ပစ္စည်းလဲ?`
  buttons: top 3 suggestions (candidate/fuzzy), [🔍 ရှာမယ်] (search all products),
  [➕ ပစ္စည်းအသစ်] (owner: full form with price; staff: name + "ask owner for price" -> item
  waits, owner gets it in Needs you), [🚫 ဒီပစ္စည်း မရှိဘူး] (-> not_stocked pattern).
Q-intent (product known but intent other/unknown, or no product and no intent):
  `ဖောက်သည်က ဘာလုပ်ချင်တာလဲ?` buttons (Burmese labels): ဝယ်မယ် (buy) · ဈေးမေးတာ (ask_price)
  · ရှိလားမေးတာ (ask_stock) · ဖြုတ်မယ် (remove) · အော်ဒါ cancel (cancel_order) ·
  ပစ္စည်းရောက်ပြီလားမေး (ask_delivery) · အရင်ကဟာ ပြန်ယူမယ် (previous_item, 4.3) ·
  နှုတ်ဆက်တာ (greeting) · မေးခွန်း — ကိုယ်တိုင်ဖြေမယ် (question -> opens Custom reply) ·
  ဘာမှမလုပ်နဲ့ (ignore).
Q-size only when size missing and needed: buttons with the sizes sold + full bottle.
Learn box: `☑ နောက်တစ်ခါ ဒီလိုရေးရင် အလိုအလျောက် လုပ်ပေးပါ` (checked by default) with the
  phrase that will be learned shown and editable (system proposes: the message minus product
  names, sizes, numbers, phones, punctuation; for nicknames: the unknown text).
Preview line before confirming: what will happen (e.g. "Y Eau de Parfum 10ml ကို ခြင်းထဲထည့်ပြီး
  စာရင်းပို့မယ်"). [✅ အတည်ပြုမယ်] -> human parse result (method=human) + learned patterns
  (pending, taught_by) + the normal flow continues (cart/reply via the same code as one-tap;
  sent with the usual 10 s Undo). Undo also removes patterns created by that card.
- Greeting: intent `greeting` (seed: hi, hello, ဟယ်လို, ဟိုင်း, မင်္ဂလာပါ, mingalarpar) when the
  message is ONLY a greeting -> auto reply template `greeting_reply`
  (`မင်္ဂလာပါ။ ဘာကူညီပေးရမလဲ။`) unless we messaged them in the last 6 h. Setting ON.
- Not stocked memory: a not_stocked pattern (approved) -> next customer asking that name gets
  auto `not_stocked_item` reply (setting `auto_not_stocked`, default ON) and counts in Wanted.
Acceptance:
B1 "ysl edp 10 ml ရောယူပါမယ်" (fuzzy) -> no auto; card: Q-product with Y EDP first;
   choose it -> item added, list sent, patterns: nickname "ysl edp"(pending) +
   intent_phrase "ရောယူပါမယ်"(pending) only if not already known.
B2 another customer "ysl edp 5ml ယူမယ်" -> one-tap "📘 learned" suggestion (not auto);
   accept -> confirmed_uses 1. After 3 accepted uses -> approved -> 4th customer: AUTO.
B3 owner approves a pending pattern -> next message auto immediately.
B4 "liquid brun 5ml ရှိလား" -> card -> "မရှိဘူး" -> reply not_stocked text; next customer
   "liquid brun ရှိလား" after approval -> auto not_stocked reply + Wanted count 2.
B5 "hi" -> auto greeting; "hi" again 1 h later -> no reply; "hi swy 5ml ဘယ်လောက်လဲ" -> price
   reply (greeting not alone).
B6 card Undo within 10 s -> nothing sent, patterns created by the card removed.
B7 staff "New product" -> item waits, owner sees "price needed" in Needs you; owner adds
   price -> list sent automatically.
B8 conflicting nickname (text already approved for another product) -> not saved; owner asked.

---------------------------------------------------------------------------------------
## 4.3 "The previous one" (reorder from history)
GOAL: "ဟိုနေ့ကဟာ ထပ်ယူမယ်" works without guessing.
- intent `previous_item`, seed phrases: ဟိုနေ့ကဟာ, အရင်ကဟာ, အရင်ယူတဲ့ဟာ, ပြီးခဲ့တဲ့တစ်ခါကဟာ,
  အဲ့ဒါ, အဲ့ဟာ, same one, last time, same as before (+ learnable via 4.2).
- Candidates (deduplicated product+size, newest first): items of the last PAID order ->
  current/last cart -> products asked in the last 30 days.
- 1 candidate -> add (qty from message, default 1) + list with line
  `{product} {size} (အရင်ယူထားတဲ့ဟာ) ဟုတ်တယ်နော်။ မဟုတ်ရင် ပြောပေးပါ။` (auto allowed).
- 2-5 candidates -> template `choose_previous`:
  `အရင်က ယူထားတာတွေပါ –\n1. … \n2. …\nဘယ်ဟာလဲ နံပါတ်လေး ပြောပေးပါနော်။`
  Store a `choice_prompts` row (customer, options, expires 24 h). Customer answers "1", "၁",
  "1 နဲ့ 2", "2 ခုလုံး", "အကုန်" -> add those; anything else -> normal parsing.
- 0 candidates -> Needs you (card Q-product).
Acceptance: C1 one past paid item -> auto added + line. C2 two items -> numbered list; "2" ->
second added; "၁" -> first. C3 "1 နဲ့ 2" -> both. C4 expired prompt (25 h) -> "1" is not
treated as a choice. C5 no history -> Needs you. C6 "ဟိုနေ့ကဟာ ၂ ခု ထပ်ယူမယ်" -> qty 2.

---------------------------------------------------------------------------------------
## 4.4 Roles, permissions, owner approval
GOAL: staff can run daily orders safely; only the owner changes money settings and makes
learning permanent.
- roles owner|staff (users.role exists). Users page (owner): add staff, reset password,
  disable, language. `scripts/create_user.py --role staff`.
- Staff CAN: inbox, Needs you, chats, replies, teaching cards, cart, orders statuses,
  payments (if setting `staff_can_approve_payments`, default ON), reports read-only.
- Staff CANNOT (hidden + server returns 403): prices/Excel, products edit/delete, payment
  methods, templates, FAQ, settings, auto-reply switch, users, approving/rejecting patterns,
  sales profit/cost numbers (staff see revenue/orders only).
- Learning page (/learning, owner): pending patterns grouped by kind, each with example
  message, who taught, uses; ✅ approve / ❌ reject / ✏️ edit; approved list with remove;
  counters "handled by learned patterns this week". Needs you shows "📘 N patterns to approve".
- audit_log shows the user name for every action.
Acceptance: D1 staff GET/POST each owner-only route -> 403 and no menu link. D2 staff can
approve payment when setting ON; 403 when OFF. D3 staff-taught pattern is pending; owner
approve -> approved; reject -> ignored by parser. D4 auto_approve_after=0 -> never auto
approved. D5 disabled user cannot log in.

---------------------------------------------------------------------------------------
## 4.5 Burmese dashboard, help, practice mode, staff guide
GOAL: a non-technical staff member can be trained in under an hour and work alone.
- i18n: every UI string via a small translation table (my, en). Language per user (staff
  default my) + switch in the header. Status names, buttons, menus, errors, empty states.
- "?" help next to each section: one Burmese sentence.
- Help page: renders docs/STAFF-GUIDE-my.md (write it): what each screen is, "a message came —
  what do I do?", teaching cards, payments check (open KPay app, find the transaction, type
  the ID), packed/sent/delivered, what NOT to do, who to ask.
- Practice mode (/practice): runs teaching cards and one-tap actions on practice messages
  (from tests/fixtures/synthetic_messages.csv + v4 examples) inside a rolled-back transaction:
  nothing saved, nothing sent; shows ✅/❌ against the expected answer and a score.
Acceptance: E1 every template/page renders with lang=my with no English UI words left except
product names (test scans rendered HTML for a list of known English UI words). E2 practice
mode writes nothing (row counts unchanged, outbox empty). E3 help page renders the guide.
E4 language switch persists per user.

---------------------------------------------------------------------------------------
## 4.6 (LATER, only when the owner asks) AI helper
Same teaching cards, but an AI pre-selects the answers. Provider must be available in Myanmar
and payable by the owner. AI_PROVIDER setting. Not part of this build.
