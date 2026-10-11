# Decant Inbox — Project Guide for Claude Code

## Goal of v1 (MVP)
A perfume decant shop in Myanmar receives requests in the owner's PERSONAL Telegram
account (no bot). v1 does ONLY this:

  Telegram message -> saved -> parsed (product, size, intent) -> shown in web dashboard

Example messages (mixed Burmese/English):
- "5ml stronger with you intensely ရှိလား"   -> ask_stock, STW Intensely, 5ml
- "stw intensely ၅ ml ဝယ်ချင်လို့ပါ"            -> buy, STW Intensely, 5ml

NOT in v1 (planned later, do not build yet): stock/inventory, orders & statuses,
payments, delivery, reports, Viber, auto-replies.

## Design principles (so later features plug in cleanly)
1. Keep raw messages forever. Parsing results are stored separately, so we can
   re-parse all old messages when the parser improves.
2. Every parse result records `method` (rules|ai|human) and `parser_version`.
3. Every message/customer has a `channel` field ("telegram" now; "viber" later).
4. Services are independent and talk only through the database:
   listener (writes messages) / parser worker (writes parse results) / api (reads, edits).
   Any one can restart without affecting the others.
5. All schema changes go through Alembic migrations. Never edit tables by hand.
6. Future modules (inventory, orders) get their own folders and tables and reference
   existing tables by foreign key; they must not change v1 table meanings.
7. Config and secrets only via .env.

## Stack
Python 3.12, Telethon, FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL 17,
Jinja2 + HTMX dashboard, myanmar-tools + Zawgyi->Unicode converter, rapidfuzz,
Docker Compose. AI fallback (Anthropic API) is optional, Phase 3b.

## Server & access (important)
- NAT VPS, Ubuntu 26.04, shared public IP 93.127.132.69. Provider forwards external
  port 10066 -> internal 22 (sshd). There are NO public ports 80/443.
- Firewall (ufw): deny incoming by default; allow 22/tcp and traffic on tailscale0 only.
- Dashboard is PRIVATE via Tailscale: the web service publishes on 127.0.0.1:8080 only,
  then `tailscale serve --bg --https=443 http://127.0.0.1:8080`.
- Docker ports bypass ufw, so ALWAYS publish as "127.0.0.1:PORT:PORT", never bare ports.
- Public access later (only if asked): Cloudflare Tunnel or Caddy under a compose
  profile "public". Not part of v1.
- No passwordless sudo: put root steps in a script and ask the owner to run it.

## Repo layout
```
app/
  core/        config, db session, shared models base
  models/      SQLAlchemy models (one file per table group)
  listener/    Telethon client + history import script
  parser/      normalize.py, rules.py, ai_fallback.py (later), worker.py
  web/         FastAPI routes, templates, static
migrations/    Alembic
scripts/       seed_catalog.py, reparse_all.py
tests/         parser tests from data/sample_messages.csv
data/          products.csv, aliases.csv, sample_messages.csv
secrets/       telegram .session (NEVER commit; chmod 600)
compose.yaml  .env (NEVER commit)  .env.example  PLAN.md
```

## v1 data model
- customers(id, channel, external_user_id, username, display_name, ignored bool,
  created_at)  UNIQUE(channel, external_user_id)
- messages(id, channel, external_chat_id, external_message_id, customer_id,
  raw_text, normalized_text, received_at, created_at)
  UNIQUE(channel, external_chat_id, external_message_id)  -> imports are idempotent
- products(id, brand, name, active, created_at)
- product_aliases(id, product_id, alias_text, normalized_alias, source[seed|learned])
- parse_results(id, message_id, intent[buy|ask_stock|ask_price|other|unknown],
  product_id NULL, size_ml NULL, quantity default 1, confidence float,
  method[rules|ai|human], parser_version, is_current bool, created_at)
  -> re-parsing adds a new row and flips is_current; history is kept
- message_reviews(id, message_id, status[new|done|ignored], note, reviewed_by,
  reviewed_at)
- users(id, username, password_hash, role[owner|staff], created_at)

## Phases (do one at a time; stop and report after each with how to verify)
- Phase 0: VPS hardening (show the plan and wait for owner OK before touching SSH,
  firewall or auto-updates), fail2ban, unattended security upgrades, Tailscale,
  Docker, compose.yaml (postgres), .env.example, git connected to GitHub.
- Phase 1: Models + Alembic migration + scripts/seed_catalog.py from data/*.csv.
- Phase 2: Telethon listener: private chats only, incoming only, save raw message +
  customer. Plus listener/import_history.py (last N days) using same save function.
- Phase 3: Parser (rules) + worker that parses new messages + scripts/reparse_all.py +
  tests from data/sample_messages.csv. Phase 3b (optional): AI fallback for low confidence.
- Phase 4: Dashboard: login, inbox (newest first, filter by intent/product/status,
  search), message detail with parsed result, edit result (saved as method=human),
  mark done/ignored, ignore customer, manage products & aliases, "save as alias" on edit.
- Phase 5: Run 24/7 (restart policies), daily pg_dump backup, basic health page.

## Parsing rules
1. Normalize: Zawgyi -> Unicode; Burmese digits ၀-၉ -> 0-9; unit variants
   (ml, mL, ml., မီလီ, မီလီလီတာ) -> "ml"; lowercase; collapse spaces.
2. Size: regex on normalized text, e.g. (\d+)\s*ml.
3. Product: match product_aliases (exact substring first, then rapidfuzz above threshold).
4. Intent: ဝယ်ချင် / ယူမယ် / order -> buy; ရှိလား / ရလား -> ask_stock;
   ဘယ်လောက် / price -> ask_price; else other/unknown.
5. Confidence from what was found; low confidence shows as "needs review" in dashboard.

## Git workflow
- Repo: github.com/kaungkyaw3124/decant-inbox (private), branch main.
- Planning files (CLAUDE.md, PLAN.md) are edited by the planning chat on claude.ai.
  The VPS Claude Code edits code; it changes planning files only if the owner asks.
- Always `git pull --rebase` before starting work; commit and push after each step.
- Before every commit, check that .env, secrets/, *.session and data with customer
  messages are NOT staged.
- Update the "Status" section of PLAN.md when a step is finished.

## Hard rules
- Telegram account (changed by docs/SPEC-orders.md, v2): the server may SEND a text message
  to a private chat ONLY as the result of an admin click in the dashboard (outbox table ->
  listener -> app/listener/sender.py, max 1 msg / 3 s and 20 / min). Never edit, delete,
  forward, pin, or mark-read. Never message a chat that has not messaged us first.
  Only the listener process uses the Telethon session; web code never imports Telethon
  (tests/test_listener_readonly.py enforces this).
- Only private chats with real users; ignore groups, channels, bots. Our own outgoing
  messages are saved too (direction=out). Photos: metadata only; download a photo only when
  an admin opens it, into secrets/media/ (dir 700, git-ignored).
- Never print, log, or commit api_hash, session files, .env, or API keys.
- The owner types the Telegram login code into the interactive prompt themselves.
- Small steps, tests for the parser, explain how to verify each phase.
