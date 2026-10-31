# Epic 4.20 — AUTOMATION GOAL: the bot answers customers by itself. Goal-driven loop. Build right after 4.17.

Owner, 2026-10-31 11:50: "now it replies nothing. I want auto reply. Make a goal. Let Claude Code work until it
meets its goal." Live today: the same order message was sent 5 times (10:27-11:42) and got only "please wait"
(once 5 min late) or nothing. Every new wording becomes a person's job; we fix one screenshot at a time. Stop that.

## THE GOAL (all must be true at the same time; measured by the simulator in A1 and the live replay in A5)
- **G1 Automatic:** ≥ 90% of customer messages in the simulator get a correct reply with NO person involved.
- **G2 Never wrong:** 0 replies with a wrong price, product, size, quantity, total, phone, address or Order ID
  (strict judge, A4). One wrong = goal not met.
- **G3 Never silent:** 100% of messages get a reply. When a person is truly needed (≤ 10%), the customer gets the
  holding reply within 10 s (3 s after 4.18) and the admin gets ONE clear Needs you item.
- **G4 Live proof:** the last 30 days of real incoming messages, replayed on a COPY of the database with sending
  disabled, reach ≥ 85% automatic and 0 wrong (report numbers only; never commit customer text).
- Telegram hard rules, payment rules (real payments are never approved automatically, paid orders stay locked)
  and the AI privacy rules are unchanged. Never invent a price, product or Order ID.

## The principle that gets us there: ASK THE CUSTOMER, NOT THE ADMIN
When the bot is not sure, it asks the CUSTOMER a short question it can understand the answer to. The admin is
only for things a customer question cannot solve: complaints, refunds, angry customers, money problems,
things outside the shop, and repeated confusion (customer answered 2 questions and it is still unclear).

## A0 Fast tests first (the loop needs it)
- Run pytest in parallel (pytest-xdist, one test database per worker, fixtures made worker-safe). Target: full
  suite ≤ 8 minutes (today ~22). Same tests, same results; flaky = fix, never skip.

## A1 The customer simulator
- `scripts/simulate.py` + `tests/sim/scenarios/*.yaml`. A scenario = a list of customer turns (text, or
  photo/voice/sticker markers, optional time gaps) + the EXPECTED facts after each turn: reply kind
  (auto/holding/needs-person), must-contain / must-not-contain pieces, cart lines (product, size, qty), phone,
  address (township/city), order status, Order ID. Runs on a test DB with the TEST catalog + test prices, the
  fake Telegram client and the real worker code.
- AI: real OpenAI in eval mode (cost cap $1 per full run, $3 per day) AND recorded answers (cassettes) so pytest
  runs offline and fast. Re-record when prompts change.
- Scenarios (≥ 200; ≥ 80 written by hand, the rest generated then checked):
  - every live bug this month (4.8-4.17 screenshots, incl. 09:46, 09:48, 10:27, 11:42 today) — must pass forever;
  - greetings, price, stock, buy one / many, Burmese / English / mixed / Zawgyi / typos / nicknames;
  - sizes not sold (20ml, 3ml, full bottle without price), unknown products, two products with similar names;
  - phone and address in the same message, Yangon + Mandalay (grid) + other cities, partial addresses;
  - changes: remove, change size/qty, change phone/address, old unconfirmed carts, a new order after a paid one;
  - payment words, screenshot, test code, "I paid", partial pay;
  - delivery time / fee / COD / pickup / "where is my order #1001";
  - thanks / ok / 👍 / emoji only, two quick messages, long chatty messages, voice / sticker / photo of a perfume;
  - complaints, refunds, angry, wrong item (must go to a person + holding reply — counted as CORRECT).
- Generated scenarios: an AI writes customer conversations from a list of personas + the catalog; it also
  writes the expected facts as structured data; a rules check rejects generated scenarios whose expectations
  contradict the catalog/prices. Keep the generated files in git (they contain no real customer data).

## A2 Close every "goes to a person" reason (loop target)
Measure the reasons (auto_runs.reason, Needs you kinds) in the simulator and the live replay. Fix the biggest
first. Expected fixes (use the existing templates/settings style; English + Burmese):
- size not sold → size question with prices (4.17, verify);
- product unclear / AI 55-85% sure → ask the customer: "SWY Intensely 10ml ကို ဆိုလိုတာလား? (ဟုတ် / မဟုတ်)" or a
  numbered choice of the top 3 (4.11 style). Answer understood → continue automatically;
- product unknown → "ဘယ် perfume လဲ နာမည်လေး ပြန်ပို့ပေးပါ" + up to 5 best sellers as numbered choices;
- "other/unknown" intent with an open cart → resume line (what we are waiting for) instead of silence;
- phone/address unclear → ask the customer the exact missing piece (4.12/4.13 flow), never the admin first;
- delivery fee / time / COD / pickup → answers from owner settings (new /settings section "Delivery":
  fee per city/township group, COD yes/no, delivery days). Not filled in → "ပို့ခကို admin က အတည်ပြုပေးပါမယ်"
  + continue the order (do not block the order);
- voice / sticker / video → polite "စာနဲ့ ရေးပေးပါနော်" reply (no download); photo of a perfume (not during
  payment) → "ဘယ် perfume လဲ နာမည်လေး ရေးပေးပါ" (AI image reading of bottles: later, not this epic);
- emoji/thanks/ok after a finished step → short friendly reply or nothing if nothing is pending (counts correct);
- a customer repeating the same message → answer it again (never skip because "already answered" when the
  previous answer was only a holding reply).
- Holding reply: make sure it is never late/missing (11:42 case). If the cause is the worker being busy or
  restarted, fix that too (the watchdog must survive restarts).

## A3 The loop (do not stop early)
repeat: run simulator (+ live replay when fixes touch parsing) -> scoreboard -> pick the biggest failing
reason -> write/adjust scenarios + unit tests -> fix -> full pytest green -> simulator again.
After EVERY iteration append one line to REPORT.md "4.20 scoreboard": iteration, automatic %, wrong, silent,
needs-person %, top 3 reasons left, AI cost so far. Commit + push each iteration that improves the score.
Stop when G1-G4 are all met, OR after 15 iterations / the AI budget is used: then stop and report exactly what
is left and what you need from the owner (never lower the goal or the judge by yourself).

## A4 The judge (strict)
- Every number in a reply must come from the price list / cart / order (parse the reply; compare).
- Every product/size named must be in the expected facts or be a question offering choices.
- Phone/address shown must be the latest one the customer gave in this conversation (or the saved one only when
  the customer gave none and the reply asks to confirm it).
- Order IDs only of this customer's orders. A reply to a complaint that promises a refund/replacement = wrong.
- needs-person when the scenario expects auto = not automatic; auto when the scenario expects a person = WRONG.

## A5 Live replay (privacy)
- `scripts/replay_live.py`: copies the live DB to `<db>_replay` (pg_dump/restore, local), disables the outbox
  sending, re-runs the last 30 days of incoming messages in order through the new pipeline, and prints
  aggregate numbers + reason counts + message ids only. Output under data/exports/ (git-ignored). Never prints or
  commits customer text. Delete the copy afterwards.

## A6 Owner inputs (ask in REPORT.md; do not block on them)
Delivery fee table, COD yes/no, delivery days, shop hours. Until filled: the safe defaults above.

## Done =
G1-G4 met, full pytest green (≤ 8 min), ui gate quick mode green, AI eval gates pass, deployed, REPORT.md entry
with the scoreboard + OWNER TEST 4.20, PLAN.md NEXT TASK DONE.

## OWNER TEST 4.20 (second Telegram account, Auto-reply ON)
1. `Swy intensely 20ml ယူပါမယ်` / `66 str 28 str ကိုပို့ပေးပါ` / `09958745521` → automatic size question with
   prices; answer `10ml` → list + "deliver to 66 str 28 str, Mandalay, phone 09958745521?"; answer `ok` →
   payment info. No person needed.
2. `dior ဟိုဟာလေး ရှိလား` → a numbered choice; answer `2` → price + "ယူမလား".
3. `ပို့ခ ဘယ်လောက်လဲ` → delivery answer (or "admin will confirm" if the fee table is empty).
4. A voice message → "please type" reply.
5. `ပစ္စည်းယိုနေတယ်` (leaking) → holding reply within seconds + ONE Needs you card (correct: a person handles it).
