# Report

Short entries from the VPS Claude Code session, newest last.

## 2026-10-10 — Login audit (Phase 0)
- Did: reviewed `who`/`w` and /var/log/auth.log.
- Verified: only two successful SSH logins ever (both `administrator`, password):
  45.125.5.23 (owner confirmed it's them) and 199.235.135.31. ~300 failed brute-force
  attempts from 7 IPs, none succeeded. No root logins.
- Problems: password auth is enabled; fixed in Step 2.

## 2026-10-10 — Step 0: rollback safety net
- Did: `~/hardening/rollback.sh` (disable ufw, remove sshd drop-in) and
  `~/hardening/step0-arm-rollback.sh` (installs it as root, fires in 10 min via systemd-run).
- Verified: scripts syntax-checked; armed at the start of each risky step.

## 2026-10-10 — Owner SSH key login test
- Verified: auth.log `Accepted publickey for administrator from 199.235.135.31`
  (ED25519 SHA256:IWs3D6dc…7ak) at 16:50 UTC via port 10066.

## 2026-10-10 — Git connected to GitHub (push BLOCKED)
- Did: `git init`, based on origin/main (de6775f), kept repo .gitignore and added
  `.claude/settings.local.json`; added `.env.example`; committed compose.yaml.
  Auth = repo deploy key `~/.ssh/decant_inbox_deploy` (SHA256:8srQeMXT…09c) via
  ssh alias `github-decant-inbox`.
- Verified: no .env / secrets / session / customer data staged.
- Problems: GitHub rejects the deploy key (`Permission denied (publickey)`), and the
  repo is still readable anonymously (API returns 200), so it is still PUBLIC.
- Needed from owner: add the deploy key to THIS repo with write access, and make it private.

## 2026-10-10 — Git push to GitHub (unblocked)
- Did: owner re-added the deploy key; pushed main (de6775f..6891923).
- Verified: `ssh -T` -> "Hi kaungkyaw3124/decant-inbox! You've successfully authenticated";
  `git status` shows main in sync with origin/main.
- Problems: GitHub API still reports `"visibility": "public"` and anonymous
  `git ls-remote` works, so the repo is NOT private yet.
- Needed from owner: Settings -> General -> Danger Zone -> Change visibility -> Private.

## 2026-10-10 — Step 1: firewall (ufw)
- Did: owner ran `~/hardening/step1-firewall.sh` (17:12 UTC): rollback armed, default
  deny incoming / allow outgoing, allow 22/tcp + in on tailscale0, removed 443/tcp,
  enabled ufw. Owner then cancelled the rollback timer and deleted the old 80/tcp rule.
- Verified: /etc/ufw/ufw.conf `ENABLED=yes`; fresh key login via port 10066 accepted
  at 17:12:38 (publickey); rollback timer gone; sshd still on 22; Postgres still
  127.0.0.1:5432 only.
- Old 10066/tcp rule: unused. All SSH connections arrive on internal port 22 (provider
  NAT rewrites 10066 -> 22) and nothing listens on 10066. Removal handed to owner:
  `sudo ufw delete allow 10066/tcp`; confirm in the Step 2 entry.
- Needed from owner: repo is still public (see previous entry).

## 2026-10-10 — Step 2 + Steps 3+4: scripts ready (owner runs with sudo)
- Did: `~/hardening/step2-ssh.sh`: drop-in `/etc/ssh/sshd_config.d/00-hardening.conf`
  (key only, no root, AllowUsers administrator, MaxAuthTries 3, no X11). It loads before
  `50-cloud-init.conf` (which sets `PasswordAuthentication yes`); Include is the first
  active line of sshd_config, so the drop-in wins. Validates with `sshd -t` + `sshd -T`
  (incl. `port 22`) before reload; 10-min rollback armed.
- Changed: rollback now only removes the SSH drop-in; it no longer disables ufw
  (step 1 is proven).
- Did: `~/hardening/step34-fail2ban-autoupdates.sh`: fail2ban sshd jail (systemd backend,
  aggressive mode, 5 tries / 10 min, 1h ban growing to 1w), unattended security upgrades
  (no auto-reboot), plus `python3-venv` (needed for Phase 1 on the host).
- Verified so far: both scripts pass `bash -n`. Not run yet.
- Needed from owner: `sudo ufw delete allow 10066/tcp`, then run step 2, test, cancel
  timer; then run steps 3+4. Repo is still public.

## 2026-10-10 — Phase 1 (in progress): models, seed, example data
- Did: app/core (config via .env, db, Base with naming convention), app/models
  (customers, messages + message_reviews, catalog, parsing, users per CLAUDE.md),
  app/parser/normalize.py (digits, units, case, spaces; Zawgyi comes in Phase 3),
  Alembic config, scripts/seed_catalog.py, example data/products.csv + aliases.csv.
- Design choices:
  - enum-like columns are VARCHAR + CHECK (easier to extend than PG enums);
  - external ids are strings (Viber ids are not integers);
  - one current parse result per message enforced by a partial unique index;
  - message_reviews: one row per message (current state), not history;
  - alias uniqueness is (product_id, normalized_alias); the same alias on two products
    is allowed and treated as ambiguous by the parser.
  - seed is idempotent; CSV is the source of truth: products not in CSV -> active=false,
    seed aliases not in CSV -> deleted, learned aliases untouched. So replacing the
    example rows with the real list later cleans up the examples.
- Verified: all modules compile; 7 normalize cases pass (system python).
- Problems: no venv yet (python3-venv missing), so the migration, seed run and pytest
  wait until steps 3+4 run. Host Python is 3.14; containers will use 3.12 per CLAUDE.md.
- Note: PLAN says "YSL Stronger With You Intensely"; Stronger With You is an Emporio
  Armani perfume, so the example row uses brand "Emporio Armani". Owner replaces it anyway.

## 2026-10-10 — Phase 1 done: venv, migration, seed, tests
- Did: venv `.venv` (Python 3.14 on host). python3-venv is not installed (the steps 3+4
  script stopped early, likely at the masked apt-daily.timer), so I created the venv
  `--without-pip` and bootstrapped pip 26.2.1 from its PyPI wheel (sha256 checked
  against PyPI). No sudo needed. Pinned requirements.txt.
- Did: Alembic migration `cee9169656b3` (v1 initial schema, 7 tables) applied to
  product_requests. Seeded the example catalog. Added tests/test_seed_catalog.py
  (runs in a throwaway `product_requests_test` DB, dropped afterwards).
- Verified:
  - `alembic check` -> "No new upgrade operations detected" (models == DB);
    downgrade base -> upgrade head round-trip works.
  - Seed run twice: same output (3 products, 7 aliases) and identical table snapshot
    (same ids, no duplicates).
  - `pytest`: 11 passed (7 normalize + 4 seed: idempotent, alias normalization,
    replacing the list deactivates old products / drops old seed aliases / keeps
    learned aliases, unknown product name rolls back).
  - Real DB untouched by tests (still 3 products, 7 aliases).
- Phase 0 state seen on the server (no action, Phase 0 closed): sshd drop-in
  00-hardening.conf exists, fail2ban active.
- How to verify: `.venv/bin/alembic current` -> cee9169656b3 (head);
  `.venv/bin/python -m scripts.seed_catalog`; `.venv/bin/pytest -q`.

## 2026-10-10 — Phase 2 (code done; waiting for owner login)
- Did: app/listener/
  - save.py: one filter + save path shared by live listener and history import.
    Keeps only private, incoming, text messages from real users; drops outgoing,
    groups, channels, bots, Saved Messages, Telegram support and 777000 (the account
    that sends login codes, so codes are never stored). Media without caption is
    skipped. Upserts the customer (refreshes username/name) and inserts the message
    with ON CONFLICT DO NOTHING (idempotent). Stores raw_text unchanged plus
    normalized_text. Writes only customers + messages.
  - client.py: Telethon client; session at secrets/telegram.session (dir 700, file
    600); catch_up=True to fetch updates missed while down.
  - login.py: one-time interactive login (owner types phone, code, 2FA).
  - main.py: live listener; logs only ids, never text or credentials; one bad message
    does not stop it.
  - import_history.py: `--days N` (default 30), `--dry-run`; all folders incl. archived;
    re-runnable to fill gaps.
- Verified: pytest 24 passed (new: 10 ignore cases, keep case, save idempotency +
  customer update, and a read-only guard test that fails if listener code calls any
  send/edit/delete/forward/pin/mark-read method). Without TG_API_ID/TG_API_HASH, all
  three entry points exit with a clear message and create nothing.
- Not verified yet: anything against real Telegram (needs owner credentials + login).
- Needed from owner: TG_API_ID + TG_API_HASH in .env; then run the login and type the code.

## 2026-10-10 — Phase 2 verified live; Phase 3 done (rule parser + worker)
- Phase 2 against real Telegram (counts only, no text shown):
  - Dry run, 30 days: 1 chat, 17 messages scanned, 5 kept, 0 written.
    Low count checked: only 5 private user dialogs had any activity in the last
    30 days (56 older, 1 bot), so it is real, not a filter bug.
  - Real import: 5 new rows; second run: 0 new (idempotent). DB: 1 customer, 5 messages.
  - Live listener started: `nohup .venv/bin/python -m app.listener.main >> logs/listener.log`.
- Phase 3:
  - normalize.py: Zawgyi -> Unicode (myanmar-tools detector, p > 0.95, python-myanmar
    converter). Catalog re-seeded so aliases use the new normalization.
  - rules.py (`rules-1`, pure functions): intent keywords (priority buy > ask_price >
    ask_stock); size `N ml`; quantity (`2 ခု`, `3ဗူး`, `x2`, `2 pcs`); product by exact alias
    (longest first, not glued to other Latin letters) then rapidfuzz partial_ratio >= 88
    (aliases >= 5 chars). Same alias on two products -> no product, needs review. Two
    products in one message -> first one, needs review.
  - Confidence: intent 0.3 + product (exact 0.5 / fuzzy 0.35 / multiple 0.25) + size 0.2;
    -0.15 for several sizes. No intent but product/size -> `unknown`, capped at 0.5.
    Nothing found -> `other`, 0.7. Needs review below 0.6 (`NEEDS_REVIEW_BELOW`).
  - service.py: shared by worker and reparse; re-normalizes messages.normalized_text;
    adds a new row only if outcome or parser_version changed; never replaces a `human` result.
  - worker.py: polls every 5s for messages without a current result; started with
    `nohup .venv/bin/python -m app.parser.worker >> logs/parser.log`. Logs ids/counts only.
  - scripts/reparse_all.py (`--dry-run`), scripts/export_samples.py (writes the git-ignored
    data/sample_messages.csv, mode 600, pre-filled with the parser's guess for labelling).
  - logs/ added to .gitignore.
- Verified: pytest 59 passed, 1 skipped (sample-label test, no labelled file yet). Real data:
  5 parsed, all `other` (expected: catalog is still the 3 example products); reparse_all ->
  unchanged=5.
- Not done / limits: both services run under nohup, so they stop on reboot (restart
  policies are Phase 5). Do not run import_history while the listener runs (they share the
  Telethon session file; stop the listener first). The intent keyword list is a first guess
  until real labelled samples exist.
- Needed from owner: real data/products.csv + aliases.csv (then `python -m scripts.seed_catalog`
  and `python -m scripts.reparse_all`); label exported samples.

## 2026-10-11 — Test catalog + fixture test; Phase 4 dashboard (Tailscale waits on owner)
- Test data: re-seeded (20 products, 57 aliases); reparse_all -> 5 unchanged (still `other`).
  tests/test_parser_samples.py now also runs tests/fixtures/synthetic_messages.csv on every
  pytest: 33/33 pass. Seed/DB tests now use their own small catalog instead of data/,
  so replacing the catalog CSVs can't break them.
- Migration 500de2fa8725: products.source (seed|manual). Seed only deactivates `seed`
  products, so products added in the dashboard survive a re-seed. Round-trip
  (down/up) tested; `alembic check` clean.
- Worker: re-parses everything when the active catalog (aliases) changes, and once at
  start. So the dashboard only edits the catalog and the worker stays the only writer of
  rules results; human results are never replaced.
- app/web (FastAPI + Jinja2 + htmx 2.0.4 vendored, npm integrity checked):
  - login (argon2 hashes, signed session cookie: HttpOnly, SameSite=Lax, Secure, 30 days;
    10 failed tries per username -> 15 min block), CSRF token on every POST, CSP
    `'self'` only, no-store, no access log (search terms are customer text).
  - inbox: newest first; filters status (default new), intent (default "requests" =
    hides `other`), product, needs review, ignored customers, search (raw, normalized,
    customer name); Done/Ignore/Undo buttons per row (htmx); 50 per page.
  - message: raw + normalized text, current result, edit (new row, method=human,
    confidence 1.0) with optional "save as alias" (learned), status + note,
    ignore customer, parse history.
  - products: list with alias/message counts, search, add product (manual); product page:
    activate/deactivate, add alias, delete learned aliases (CSV aliases only via CSV),
    "shared" warning when an alias belongs to two products.
  - /healthz (DB check, no login) for Phase 5.
- scripts/create_user.py (password typed at prompt), scripts/setup_tailscale.sh.
- Running: `nohup .venv/bin/uvicorn app.web.main:app --host 127.0.0.1 --port 8080
  --no-access-log >> logs/web.log`; listening on 127.0.0.1:8080 only. WEB_SECRET_KEY generated
  into .env (not printed).
- Verified: pytest 103 passed, 1 skipped (9 web tests: login required, wrong password,
  missing CSRF -> 403, filters, Burmese-digit search, htmx review, human edit + alias,
  ignore customer, open-redirect blocked, products/aliases, manual product survives
  re-seed, logout). Live: /healthz ok; / -> 303 /login.
- Not verified: rendering in a real phone browser (no browser on the VPS); Tailscale.
- Note: running the web on the host, not compose: the `administrator` user can't reach the
  Docker socket. Phase 5 will decide (docker group or systemd user units).
- Needed from owner: `.venv/bin/python -m scripts.create_user <name>` (in an SSH session),
  then `sudo bash scripts/setup_tailscale.sh`.

## 2026-10-11 — Phase 5: services, backups, health (reboot test pending)
- systemd **user** units in deploy/systemd/ (decant-listener, decant-parser, decant-web,
  decant-backup.service + .timer), installed by scripts/install_services.sh (no sudo; re-run
  after code or unit changes). Restart=always, RestartSec=10, no start limit, so they also
  wait out Postgres starting after them at boot. Logs: `journalctl --user -u decant-…`.
  User units (not system units) so code deploys/restarts never need sudo; boot start
  needs linger (root, once).
- Found: the hand-started (nohup) listener and worker had died silently after the last
  terminal session ended (last log 18:47). Ran import_history --days 2 with the listener
  stopped: 0 new rows, so nothing was missed.
- Heartbeats: new table service_heartbeats (migration 7d06122535bc, round-trip tested);
  listener beats every 60s while connected, worker every 30s.
- Health: /healthz (no login; only names + ok/FAIL; 200 or 503) and /health page (login;
  details): database, listener (<3 min), parser (<2 min), parse queue (oldest unparsed
  <5 min), backup (newest <26 h), disk (>=10% free), last message time.
- Backup: scripts/backup_db.py: pg_dump -Fc to backups/ (dir 700, files 600, git-ignored),
  written as .partial, checked with pg_restore --list, then renamed; keeps newest 14.
  Timer daily 03:00 Asia/Yangon (20:30 UTC), Persistent=true.
- Verified: pytest 106 passed, 2 skipped (real pg_dump test: client not installed yet;
  owner samples). Services active; kill -9 of each -> restarted (NRestarts=1) within ~10s;
  /healthz: everything ok except backup (no pg_dump yet).
- Needed from owner: `sudo sh -c 'apt-get update -q && apt-get install -y
  postgresql-client-18 && loginctl enable-linger administrator'`, then the first
  backup run, then a reboot test.
- Not done: off-server backup copies (backups are on the same disk as the DB).

## 2026-10-11 — Phase 5: Cloudflare quick tunnel, client-IP lockout, status script
- Owner's sudo command had NOT taken effect: postgresql-client-18 not installed (nothing in
  apt history), Linger=no. So the first backup could not run yet; /healthz still shows
  `backup: FAIL` (everything else ok).
- cloudflared 2026.10.0 official release in ~/.local/bin, SHA-256 checked against the
  release notes. scripts/tunnel.py runs `cloudflared tunnel --no-autoupdate --url
  http://127.0.0.1:8080`, passes the log to the journal, writes the trycloudflare.com URL to
  TUNNEL_URL (mode 600, atomic, git-ignored), deletes it when cloudflared stops.
  New unit decant-tunnel (Restart=always), added to install_services.sh.
- Web: uvicorn runs with --no-proxy-headers; auth.client_ip trusts CF-Connecting-IP only
  from a 127.0.0.1/::1 peer. Lockout is now 10 failures / 15 min per client IP plus 30 per
  username (all IPs), so one attacker can't lock the owner out. Secure cookie kept.
- scripts/status.sh: services, linger, /healthz, newest backup, TUNNEL_URL, SSH fallback.
- Verified: pytest 111 passed, 2 skipped (5 new tests: URL parsing, file mode, header trust,
  per-IP and per-user lockout). Over the internet: tunnel /login 200, / -> 303 /login,
  cookie `httponly; samesite=lax; secure`; kill -9 cloudflared -> restarted (NRestarts=1),
  new URL written, old URL dead.
- Not verified live: that CF-Connecting-IP carries the real phone IP (covered by unit test).
- Needed from owner: the sudo command again, then first backup, then reboot.

## 2026-10-11 — Phase 5: first backup, ready for reboot test
- Owner ran the sudo command: pg_dump 18.6 installed, Linger=yes.
- First backup: product_requests_2026-10-11T1643Z.dump (27 KiB, mode 600). Restore test:
  restored into a scratch DB `restore_check`; row counts match live (messages 7, customers 2,
  parse_results 7, products 20); scratch DB dropped. Also ran via `systemctl --user start
  decant-backup` -> Result=success. Next timer run 20:30 UTC (03:00 Yangon).
- pytest tests/test_ops.py: 4 passed (real pg_dump test no longer skipped).
- status.sh: all services active, every /healthz check ok (backup now ok), TUNNEL_URL set.
- Postgres container has restart: unless-stopped; docker/containerd enabled at boot.
- Next: owner reboots; after it, check scripts/status.sh shows everything ok + a new URL.

## 2026-10-11 — v2 Step 1: price list (Excel import/export) + Settings
- DB (migration 4fb30f3b315c, applied live after a fresh backup; downgrade/upgrade round-trip
  tested): `product_prices` (append-only history: product, size_ml NULL = full bottle,
  is_full_bottle, price_mmk NULL = "no longer sold", in_stock, effective_from, created_by),
  `products.full_size_ml`, products.source gains `excel`, `payment_methods`,
  `reply_templates` (only edited texts; defaults in app/replies/templates.py), `audit_log`.
- Prices page (/prices): **Download current prices (.xlsx)** (all active products, incl. ones
  added in the dashboard; sizes 2/5/10ml + any other sold size; Help sheet) and **Upload** ->
  preview -> **Confirm**. Nothing is written before Confirm (the preview carries the parsed
  file in a signed hidden field, valid 1 h; Confirm refuses if prices changed meanwhile).
  Preview shows: price changes (old → new), new products, "not sure which product" rows
  (fuzzy match; you must pick: update X / new product / skip), products not in the file
  (left alone), problems in red (bad price, bad yes/no, duplicate row, formula without saved
  value...) which block Confirm, and ignored columns as warnings.
- Rules: empty cell = size not sold; a size column missing from the file = unchanged;
  in_stock empty = unchanged; a newly sold size gets the perfume's stock. Prices accept
  `18000`, `18,000`, `18,000 ကျပ်`, Burmese digits. Excel's stock is one flag per perfume.
- Product list shows prices per size (+ "out of stock" / red "no prices"); product page shows
  current prices and price history.
- Settings (/settings): payment methods (add, edit, active on/off, delete) and all 17 reply
  templates from the spec, each with its allowed {placeholders}, a live example, validation
  (unknown placeholders refused) and "reset to default". All changes go to audit_log.
- Sample file: **data/sample_prices.xlsx** — TEST prices (not real) for the 20 products
  (Born in Roma = out of stock, Luna Rossa Carbon has no 2ml). Rebuild:
  `.venv/bin/python -m scripts.make_sample_prices`.
- New deps: openpyxl 3.1.5, defusedxml 0.7.1 (safe XML parsing). Upload max 2 MB / 2000 rows.
- Verified: pytest 134 passed, 1 skipped (22 new tests: reading cells, errors, preview writes
  nothing, apply + history, removal/stock, new/ambiguous products, export→import round trip
  = no changes, web upload/confirm/tamper/stale preview, settings + validation + audit).
  Live: services restarted, /healthz all ok.
- Not done (by design, later steps): sending replies, cart, per-size stock editing in the
  dashboard (only via Excel for now), owner-only permissions (any logged-in user can import
  and edit Settings). data/products.csv + seed_catalog still work but Excel is now the main list.
- How to verify: Prices → Upload `data/sample_prices.xlsx` → preview shows 20 changed → Confirm
  → Products shows prices. Then Download, change a price / empty a cell / type "abc" in Excel,
  upload again and check the preview. Settings → add KPay → edit a reply.

## 2026-10-11 — v2: sample prices imported + test payment methods (live DB)
- Pulled (already up to date). Backup taken first (product_requests_2026-10-11T1812Z.dump).
- Preview of data/sample_prices.xlsx (same code as the Prices page): 20 changed, 0 new,
  0 to decide, 0 errors, 0 warnings. Found and fixed a preview gap: "in stock: no" was not
  shown for products without earlier prices (Born in Roma); now it is.
- Applied: 20 products updated, 79 price rows written (Luna Rossa Carbon has no 2ml).
  Re-preview of the same file: 20 "no change". Audit log: prices.import, by
  "claude-code (owner request)".
- Payment methods added: KPay 09000000001 (Test Shop), AYA Pay 09000000002 (Test Shop), both
  active (audit: payment_method.add).

## 2026-10-11 — v2 Step 2: messaging core (outbox sender, chats, Custom + Price reply)
- DB (migration 12016f356809, applied live after backup; round-trip tested; downgrade refuses
  once outgoing/photo rows exist, so raw messages are never mixed up): messages.direction
  (in|out), kind (text|photo|other), grouped_id, media_size, media_mime;
  `outbox` (queued -> sending -> sent | failed | cancelled, error, attempts, idempotency key,
  created_by, sent_message_id); `media_downloads` (photo download requests).
- Listener (app/listener): saves incoming AND our outgoing messages (from the dashboard or the
  phone), photo metadata only (also images sent as files; albums via grouped_id; stickers,
  voice, files = "other"). New app/listener/sender.py runs inside the listener (the only
  process with the session): sends queued replies with a rate limit (1 per 3 s, 20 per min),
  FloodWait -> wait and keep queued, any error -> failed with the reason. Before sending it
  re-checks: Telegram customer, has messaged us before, 1-4096 characters. A crash during a
  send leaves the row "sending" (never re-sent automatically); after 2 min the chat shows
  "unknown: check Telegram". Photos are downloaded only when an admin taps "Show photo", into
  secrets/media/ (dir 700, files 600, max 10 MB).
- Parser + inbox: only incoming messages (outgoing are never parsed or listed).
- Dashboard: **Chats** (newest activity first, "waiting for reply" when the last message is
  theirs) and the **conversation view**: thread (in + out, photos on demand, album warning,
  queued/failed replies with Try again / Cancel, auto-refresh while something is pending),
  "Open in Telegram" link, reply panel with tabs **Custom** and **Price**. Price: up to 3
  products + size (all sizes / a size / full bottle), pre-filled from what the customer asked
  in the last 24 h, built from the reply templates and current prices; out of stock -> the
  out-of-stock reply (yellow note); size/product without a price -> red, Send hidden. Every
  reply is shown in an editable box first. Greeting `မင်္ဂလာပါ။` is pre-filled only if we
  haven't messaged them in 6 h. Double-tap on Send queues once. All queue/retry/cancel/photo
  actions are in audit_log. Laptop: thread | reply side by side; phone: stacked.
  Message detail page links to "Open chat and reply".
- CLAUDE.md hard rules updated to the spec's sending rule. Guard test now: only
  sender.py may call send_message (exactly once); nothing in the listener edits, deletes,
  forwards, pins or marks read; nothing outside app/listener imports Telethon.
- History backfill (listener stopped, import_history --days 30): 2 chats, 10 new rows (our
  past outgoing messages). Live DB now: 7 in/text, 9 out/text, 1 out/other.
- Verified: pytest 154 passed, 1 skipped (19 new: capture of out/photo/album/file/sticker,
  rate limiter, send success + duplicate event, never-message-first, FloodWait, errors,
  photo download + file modes, price reply cases, greeting rule, 24 h context, chat pages,
  send/double-tap/cancel, price compose, photo request/serving incl. path traversal).
  Services restarted (tunnel untouched, URL unchanged); /healthz all ok; listener log
  "outbox sender running".
- NOT verified live: an actual send through Telegram (I did not message any real chat).
- Note: Telegram usually shows a chat as read on the phone once we reply in it; that's
  Telegram's own behaviour, we never call mark-read.
- Needed from owner — first live test: from a second Telegram account (or a friend), message
  the shop account "stw intensely 5ml ရှိလား"; in the dashboard open Chats -> that chat ->
  Price -> Make price reply -> check text -> Send. Within ~5 s the bubble turns into a normal
  sent message and the reply appears in Telegram. Also try Custom, and send a photo to test
  "Show photo".

## 2026-10-12 — One-tap quick replies: "💬 Reply price" with 10 s Undo
- Spec: docs/SPEC-orders.md "One-tap quick replies" (pulled 4ce2553).
- DB (migration ec736787bcb9, applied live after backup, round-trip tested): outbox.send_after
  (the listener only takes rows whose time has come), source_message_id,
  previous_review_status (for Undo).
- app/replies/quick.py decides when the button is shown: incoming message, current parse
  ask_price/ask_stock, product known, size known (or none = all sizes), confidence >=
  NEEDS_REVIEW_BELOW (or a human correction), every price present and in stock, no reply to
  that customer queued/sent in the last 60 s, no quick reply already made for that message,
  customer not ignored. Otherwise: no button (use the chat editor).
- Button on inbox rows and on the message page; hover/long-press shows the exact text,
  one line preview under it; message page also has "Edit before send" (opens the chat's
  Price editor with the same product/size). The 6 h greeting rule applies.
- Tap -> outbox row with send_after = now + 10 s, message marked done, audit
  outbox.quick_price. The row/page shows "Sending in N s" + Undo (countdown in
  static/quick.js), then "sending…", then "✓ price reply sent" (inbox row refreshes itself).
  Undo (or Cancel in the chat) -> cancelled + previous review status restored; after the
  listener took it: "Too late to undo". The server rebuilds the text on tap and refuses
  ("the reply changed") if it differs from what the button showed (e.g. a price changed).
- Verified: pytest 158 passed, 1 skipped (4 new: when it is offered/hidden, tap -> queued
  10 s + done, listener waits, double tap refused, undo restores, sent after 10 s, undo too
  late, changed price refused, recent reply / low confidence hide it). Live: services
  restarted (tunnel untouched), /healthz all ok, quick.js served.
- Live data: 1 real customer message currently qualifies for the button. Tapping it would
  really reply to that customer.
- Note: with the default inbox filter (status = new) a replied message disappears on the
  next reload because it is "done"; Undo stays available on the message page until sent.

## 2026-10-12 — Reply price for intent=buy + v2 Step 3: parser rules-2
- Spec: "Parser fixes found in live test" (pulled b27c411).
- Quick reply: "💬 Reply price" is now also offered for intent=buy (until the cart exists);
  deployed first as its own commit.
- Live check of the one-tap send: outbox #1 (price reply, quick) queued 18:48:40 UTC, sent
  18:48:51 UTC — the 10 s wait works on the real account.
- Parser rules-2 (app/parser/rules.py, PARSER_VERSION rules-2):
  - Multi-item: split on `,` (not inside 18,000) `၊` `။` `+` `&` new line `နဲ့` `နှင့်` `and`;
    each part -> product + size(s) + qty. "swy 5ml နဲ့ 10ml" -> 2 items of the same product.
  - Buy words with the polite particle: ယူ(ပါ)?မယ်, ဝယ်(ပါ)?မယ်, မှာ(ပါ)?မယ်, ယူ(ပါ)?ရစေ;
    `ပေးပါ`/`ပေးပါနော်` = buy only when a product or size is named; `ပို့ပေးပါ` = address.
  - Full bottle: full / full size / full bottle / fullbottle / ဗူးလိုက် / အပြည့်, or size ==
    the product's bottle size (from the price list).
  - New intents: remove, confirm, done, address (township list in Burmese + English,
    လိပ်စာ, လမ်း, ရပ်ကွက်, မြို့နယ်, ...). Order: remove > buy > price > stock > polite buy >
    address > done > confirm. A phone number alone = address.
  - Phone: 09…, +959…, 959…, Burmese digits, spaces/dashes -> "09…". Saved on the customer
    (customers.phone; the newest message with a number wins, also on reparse).
  - Context: a size with no product -> the customer's last product in the previous 24 h,
    marked "(from previous message)" (lower confidence; never used by one-tap replies).
  - Unknown product text (Latin words left after removing sizes/intents/fillers, e.g.
    "hawas ice") kept on the item as unknown_text -> shown as "❓ hawas ice", needs review.
    Burmese-only unknown names are not detected (limitation).
- DB (migration a815398921a7, applied live after backup, round-trip tested): parse_items
  (one row per item: product, size, full bottle, qty, unknown_text, from_context); intents
  check extended; parse_results.phone; customers.phone / phone_message_id / address
  (address is for Step 4). Existing results got one item each. parse_results keeps the first
  item in product_id/size_ml/quantity (v1 meaning unchanged).
- normalize(keep_newlines=True) for message text only (items can be split on new lines);
  aliases, search and Excel names are normalized exactly as before.
- Dashboard: badges show every item ("Good Girl · 5ml", "❓ hawas ice · 10ml",
  "Sauvage · full", "(from previous message)", "📞 09…"); product filter also finds 2nd/3rd
  items; the edit form has a "Full bottle" box and warns that a correction keeps one item.
- One-tap reply now covers all items (up to 3, one line each); hidden if any item is unknown,
  guessed from context, unpriced or out of stock. Chat "Price" editor pre-fills from items.
- Bug fixed (from Step 2): /healthz "parse queue" counted our outgoing messages (never
  parsed) and went FAIL once new ones were older than 5 min. Now only incoming count.
- Fixture tests/fixtures/synthetic_messages.csv: +23 rows (s33-s55) incl. both live examples,
  new columns items + phone. tests/test_parser_v2_db.py: items stored, context, phone
  (newest wins), reparse stable, human edit = 1 item, multi-item quick reply.
- Verified: pytest 186 passed, 1 skipped. Reparse on live (parser stopped): dry run
  changed=9, run changed=9, second dry run unchanged=9. Live now: "good girl 10 ml ပေးပါ" ->
  buy 1.0; the 3-item "hawas ice" message -> buy, 3 items, needs review (unknown product).
  /healthz all ok.

## 2026-10-12 — v2 Step 4: cart, one-tap cart actions, address/phone, payment info
- DB (migration a8830ff00f3e, applied live after backup, round-trip tested): `orders`
  (status cart/confirmed/waiting_payment/photo_received/paid/delivered/cancelled/abandoned,
  order_no for Step 5, total, address, phone, list_sent_at, confirmed_at,
  payment_info_sent_at; ONE open cart per customer, enforced by a unique index),
  `order_items` (price at the time it was added, kept when removed: removed_at),
  `quick_actions` (every one-tap action with exact undo data). outbox.reply_kind +
  cart / ask_address / payment_info. The earlier one-tap price reply was carried over.
- One-tap actions (app/orders/actions.py), one per message, with 10 s Undo when a reply is
  sent (60 s Undo for actions that send nothing):
  ask_price/ask_stock -> 💬 Reply price · buy -> 🛒 Add to cart + send list ·
  remove -> ➖ Remove + send list · done -> 💬 Send cart list ·
  confirm -> ✅ Confirm cart (+ ask address & phone when unknown; when the customer has a
  saved address and phone it only confirms, and the cart offers "Same address as last time") ·
  address -> 📍 Save address (+ 💳 send payment info when everything is ready).
  Only offered when certain: every item known (not guessed), priced, in stock; message in
  the last 24 h and newer than the customer's last one-tap action; no reply of theirs still
  waiting in the outbox. The button preview is made by running the action in a savepoint
  and rolling it back, so the preview IS what the tap does; the tap is refused if anything
  changed. Undo reverses items, cart status, address/phone (order and customer) and the
  message status; cancelling the queued reply in the chat does the same.
- Cart panel in the chat (phone: tabs Chat / Cart; laptop: beside the thread): items with
  ✕, total, red "no price" (+ "refresh prices"), add item (product, size or full, qty;
  100ml of a 100ml bottle = full), address + phone (saved on the order AND the customer),
  "Same address as last time", Mark confirmed, Cancel cart, and one highlighted NEXT step:
  Send cart list -> Customer agreed: mark confirmed -> Same address / Ask for address &
  phone -> Send payment info -> Waiting for the payment screenshot.
  Reply tabs: Custom, Price, Cart list, Ask address, Payment info (editable as always).
- Payment info only when: cart confirmed, every item priced, address + phone present, at
  least one active payment method (otherwise red reasons, no Send). Text = item lines +
  total + active methods + footer; no Order ID, no delivery fee. Sending it -> waiting_payment.
  Changing items of a confirmed/waiting cart -> back to "cart" (needs a new confirmation).
- Idle carts (cart/confirmed, untouched 3 days) -> abandoned (parser worker, every 10 min).
- Chats list shows the cart status badge.
- Data fix (migration 70a237588133): 10 outgoing messages imported in Step 2 had been parsed
  by the then-running old worker; their results are no longer current (kept as history).
  Nothing read them (every reader filters incoming), but now the data is clean.
- Verified: pytest 190 passed, 1 skipped (4 new end-to-end tests: buy -> undo -> buy ->
  remove -> confirm+ask -> address+payment info -> undo -> again, with exact texts sent through
  the fake Telegram client; same address next time + payment info via editor; payment info
  blockers, full-bottle rule, re-confirm after change, cancel; abandoning idle carts).
  Live: services restarted (tunnel untouched), /healthz all ok. No live message currently
  shows a one-tap button (nothing would go to a real customer by accident).

## 2026-10-12 — v2 Step 4b: partial carts, phone first then address, several phones
- Spec: "Step 4b" (pulled f02e05e).
- DB (migration d14d7d5b29d1, applied live after backup, round-trip tested):
  `customer_phones` (customer, phone, position, source message; unique per customer; max 3
  in code), `orders.phones` (text[] copy of the list; replaces orders.phone),
  `order_items.unknown_text` (+ product_id now optional; check: one of the two),
  quick_actions kind `contact`, outbox reply kinds `ask_phone`, `contact`.
  Phones the parser had saved on customers (Step 3) became their phone 1.
- A. Partial carts: a buy message with unknown items now gets "🛒 Add N known item(s) +
  send list": known priced items are added; unknown items ("hawas ice 10ml") and items
  without a price stay on the cart as red rows (blocking payment info) and are named in the
  reply with the new template `unknown_items_note`; out-of-stock items are not added and get
  the out-of-stock line. Needs at least one sellable item; products guessed from context
  still go to the chat. Red unknown rows: ✕ to remove for now (map/add/"don't have it" = Step 6).
- B. Step by step, phone first: after the customer confirms, the one-tap / next step asks only
  for what is missing: `ask_phone` -> `phone_saved_ask_address` ("ဖုန်းနံပါတ် {phones} ရပါပြီ။ …")
  -> payment info. A message with phone(s) and/or an address -> "📞 Save phone(s) / 📍 Save
  address" + the next thing (ask address / ask phone / 💳 send payment info), both in one tap
  when both are there. Address = message without numbers, "phone/ဖုန်း" words and a trailing
  ကိုပို့ပေးပါ; editable before the tap on the message page and in the cart panel
  ("From their message …"). Up to 3 phones, no duplicates; a new number after payment info ->
  `phone_added` reply. Cart panel: phone list (↑ make first, ✕ remove, add), address box,
  next step "Same phone & address as last time" when saved info exists (confirm then only
  confirms; the admin decides to reuse).
- Changed: the parser no longer saves phone numbers on the customer by itself (it only finds
  them); saving is the admin's tap (the system suggests, the admin decides). customers.phone
  is now kept = phone 1.
- New templates (Settings): unknown_items_note, ask_phone, phone_saved_ask_address,
  phone_added; ask_address default is now address only (as in the spec).
- Verified: pytest 191 passed, 1 skipped (test_cart.py rewritten: whole flow phone-first with
  undo + editable address + 3rd phone + 4th refused; partial cart with unknown, unpriced and
  out-of-stock items and blocked payment info; same phone & address next time; cart-panel
  phones (add incl. Burmese digits/+959, max 3, reorder, remove) and blockers; idle carts).
  Live: /healthz all ok; no live orders yet (Step 4 not tested on the phone yet).

## 2026-10-12 — v2 Step 4c: AUTO MODE + unknown-item resolution
- Spec: "Step 4c — AUTO MODE" (pulled 662b167). Deployed with auto-reply **OFF**.
- DB (migration 548928f8b391, applied live after backup, round-trip tested): `app_settings`
  (auto_reply = {"enabled", "since"}; inserted OFF), `auto_runs` (one final auto decision per
  incoming message), `unknown_requests` (mapped / new_product / not_stocked; not_stocked = the
  Step 6 "wanted but not stocked" list), customers.auto_reply_off / auto_resumed_at,
  quick_actions.auto, parse_items.match (exact / fuzzy / inherited / context / human; all
  messages re-parsed live so every item has it).
- Auto engine (app/orders/auto.py, runs in the parser worker every ~5 s): calls exactly the
  one-tap code (actions.suggest + actions.perform) without a tap; actor "auto" (audit_log
  user NULL, details.actor = "auto"; quick_actions.auto; outbox.created_by NULL). Rules:
  switch ON; only messages that arrived after it was switched on (never old ones) and < 24 h;
  customer not ignored / not "never auto-reply"; not paused; every product named exactly
  (exact alias, not fuzzy, not from context; human-corrected counts as exact); no unknown
  item left; intent price/stock/buy/remove/done/confirm/address only; text only (no photos);
  not already answered by a person after the message (hand reply or dashboard; auto's own
  replies don't count); customer quiet for 15 s; no reply of theirs still in the outbox (so
  quick messages are handled one after another, each with the newest state); random 8-20 s
  delay in the outbox (chat shows "🤖 Sending in N s" + Cancel = exact undo); max 300 auto
  replies / 24 h, then one-tap; at most one auto decision per message (auto_runs).
- Owner pause: a message we sent that did not come from the outbox (= typed on the phone)
  pauses auto for that chat for 2 h; chat shows "⏸ Paused — you're replying by hand" +
  "Resume auto". Per-customer "Never auto-reply to this customer" in the chat header.
- Unknown items: a price/buy message with an unknown item gets no auto reply; it is listed in
  "🟡 Needs you". Message page "❓ Not in your product list", per item: "It's in my list"
  (most similar products first, then all) -> saved as learned alias; "New product" (brand,
  name, price for the asked size required, 2/5/10/full optional, bottle size, in stock) ->
  product + prices + aliases; "We don't have it" -> recorded, and the reply gets
  `not_stocked_item` ("{name} ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။"). The message is re-parsed at
  once; then auto mode (or the one-tap button) continues with the normal reply. Learned
  aliases work for the next message immediately. The 4b partial-cart button stays as a
  manual option.
- Inbox top: "🟡 Needs you (N)" (unknown items, failed sends, paused chats with new
  messages; payments come in Step 5) and "🤖 Handled automatically (last 24 h)" feed. Header on
  every page: "🤖 Auto-reply: ON/OFF" switch. Chat: 🤖 on auto replies.
- Verified: pytest 197 passed, 1 skipped (6 new: off by default; quiet window, one reply per
  message, delay 8-20 s, actor auto, feed and 🤖; a whole order (buy -> ok -> phone -> address
  -> payment info) fully automatic; safety: before switch-on, ignored, never-auto, fuzzy,
  intent other, already answered, paused + resume, daily cap -> one-tap; unknown items wait,
  then not-stocked / new product / alias resolutions continue automatically and the alias
  works for the next customer; cancel from the chat undoes and auto does not retry).
  Live: re-parse changed=5 unchanged=5, /healthz all ok, auto_reply = OFF.
- Note: when ON, auto mode answers EVERY customer who writes (not only the test account)
  if the message is certain. Friends/family: "Never auto-reply" in their chat first.

## 2026-10-12 — v2 Step 4d: ~3 s auto replies, list asks for the phone, more items later
- Spec: "Step 4d" (pulled e8b2342). No migration (speed defaults live in code).
- A. Speed: Settings "🤖 Auto-reply speed" (app_settings auto_speed): quiet (default 1 s,
  0-30), delay min/max (default 2-3 s, 1-60, min <= max) with the "looks more like a bot"
  note. Parser worker polls every 1 s (was 5 s), outbox sender every 0.5 s (was 2 s), so a
  reply goes out ~3-4 s after the customer's message. Chose 1 s polling over LISTEN/NOTIFY
  (allowed by the spec; simpler, services stay independent).
- B. The list asks directly: cart_total is now just the total; the list ends with
  `cart_ask_phone` (no phone known) / `ask_address` (phone but no address) /
  `cart_returning` ("ဖုန်း {phones}၊ လိပ်စာ {address} ကိုပဲ ပို့ပေးရမလား။", both saved).
  A phone or address message while the cart is "cart" counts as agreement (confirmed + saved
  + ask what is missing / payment info); confirm words fill in the saved phone & address and
  go on (returning customer: "ဟုတ်ကဲ့" -> payment info). Out-of-stock / "we don't have it"
  lines now come before the closing question.
- C. Later buy messages add to the open cart (never replace) and send the updated list; the
  same product+size again keeps one line unless the customer says ထပ် / more / another / +1.
  Unknown items still wait in "Needs you" and continue automatically after resolving.
- Verified: pytest 198 passed, 1 skipped (updated cart/auto tests to the new flow + new test:
  adds later, repeat keeps one line, ထပ် = +1, address-first agreement, returning customer
  "ဟုတ်ကဲ့" -> payment info, speed settings + validation). Live: restarted, /healthz ok.

## 2026-10-12 — v2 Step 5: payment check, Order ID, confirmation message
- DB (migration fb7294a9950e, applied live after backup, round-trip tested): `payment_checks`
  (order, photo message, photo_count, image_hash, transaction_id, amount, method, decision
  pending/several/approved/rejected/not_payment, reason, reply outbox, decided_by/at),
  orders.paid_at, sequence order_no_seq starting at 1001, media_downloads.sha256 (the
  listener hashes every downloaded photo), outbox reply kind `payment`.
- Spec conflict, decided: the data model says transaction_id UNIQUE, but the flow says a
  reused transaction ID is a warning with a second confirm. A unique index would make that
  impossible, so it is an index + warning (as the flow says).
- Parser worker: payments.scan() each second: a photo from a customer whose order is waiting
  for payment (sent after the payment info) -> pending check, order "photo_received".
  Same album or a 2nd photo within 60 s -> "several": nothing downloaded, nothing queued.
  Photos sent before the payment info are not payments. Auto mode never decides payments.
- Dashboard: "Payments (N)" badge in the nav, payments listed first in "🟡 Needs you", cart
  panel "💳 Check the payment screenshot". Payment card (/payments/{id}): items, expected
  total, phones, address, screenshot (downloaded only when the card is opened, tap to zoom),
  transaction ID (required), amount received (pre-filled with the total), method.
  ✅ Approve: needs the screenshot loaded + transaction ID; warnings (transaction ID already
  used, same image as an earlier check, amount ≠ total) -> "Approve anyway" second confirm.
  -> Order #1001…, status paid, confirmation `order_confirmed` (all phones, address) queued
  10 s (Cancel in the chat). ❌ Reject: money not received / wrong screenshot / amount too
  low (asks for the rest = total - amount received) -> back to waiting payment. 🚫 Not a
  payment: nothing sent. Several photos: "Ask for one screenshot" (`several_photos`).
  No way to mark paid without a screenshot.
- Tests: reset app_settings and the Order ID sequence between tests (isolation).
- Verified: pytest 203 passed, 1 skipped (5 new: approve with loading/required/warning +
  second confirm -> #1001 and exact confirmation text; reused transaction ID + same image
  warnings on the next order -> #1002; reject wrong amount (remaining 3,000) and new
  screenshot + not a payment; several photos -> no download, ask for one, then a single
  one is checked; auto mode never touches payments; photos before payment info ignored).
  Live: /healthz ok; no order waiting for payment right now (orders: 1 cancelled, 1 cart).

## 2026-10-15 — v3 Step 6: delivery statuses, reminders + auto-cancel, unanswered, cancel order, wanted
- Spec: docs/SPEC-v3.md Step 6 (pulled). Migration f9a675362501 applied live after a fresh backup
  (product_requests_2026-10-15T1709Z.dump), round-trip (down/up) done.
- DB: orders.status + `packed`, `sent_out`; orders packed_at / sent_out_at / delivered_at, deli_name /
  deli_phone / deli_note, reminder_sent_at, cancel_note; new `order_events` (every status change / cancel
  with what Undo restores); intents `ask_delivery`, `cancel_order`; outbox kinds delivery / reminder /
  cancel; quick kinds delivery / cancel_order.
- 6.1 Orders page (/orders, nav badge = to pack): tabs To pack / To send / Sent / Delivered / All; row =
  #, customer, items, total, phones, address, age. 📦 Packed, 🚚 Sent out (optional deli name / phone /
  note), ✅ Delivered: one tap, ↩ Undo for 60 s, audit_log. Messages they send wait those 60 s in the
  outbox, so Undo also takes the message back. Sent out -> `order_sent_out` (+ `deli_line` only when a
  deli name/phone is given). Delivered: nothing unless "Send thank-you on delivered" is on. Sent out
  N days (default 5) -> delivered by the worker, no message. Packing may be skipped (paid -> sent out).
- 6.1 "ဘယ်တော့ရောက်မလဲ / ရောက်ပြီလား / ပို့ပြီးပြီလား / deli" = `ask_delivery` (parser rules-3; a bare
  "deli" only when nothing else matched and no phone, so "Bahan, deli နဲ့ ပို့ပေးပါ" stays address).
  With a paid/packed/sent-out order: one-tap / auto reply `delivery_preparing` or `delivery_sent`
  (date dd/mm/yyyy, Yangon). No such order: no reply -> Needs you (6.3).
- 6.2 Worker every 60 s: waiting_payment with no screenshot -> ONE `payment_reminder` after 12 h,
  cancel + `order_auto_cancelled` after 48 h (Settings > 📦 Orders & payments). Only with auto-reply ON
  and when the chat may be auto-answered (not ignored / never-auto / owner paused); otherwise nothing
  is sent and Needs you shows "no payment for N h" with "Send payment reminder" / "Cancel order + tell
  them". Auto-cancelled orders show as info in Needs you for 24 h. Any payment screenshot stops it.
- 6.3 Needs you "💬 unanswered": per customer, incoming messages with no reply from us (any way, incl.
  queued) after 2 min, while they have an open cart or a paid order not delivered yet; plus
  other/unknown/ask_delivery/cancel_order messages of the last 7 days. Buttons done / ignore. Decision:
  a quick/auto reply to an EARLIER message does not count as answering a later one (so "stw 5ml
  ယူမယ်" + "authentic လား" right after still shows the question).
- 6.4 "မယူတော့ဘူး / မမှာတော့ဘူး / cancel / အော်ဒါ cancel" without a product = `cancel_order`: open cart /
  confirmed / waiting payment with no screenshot -> one-tap / auto cancel + `order_cancelled` (undoable
  like other taps). Screenshot sent / paid / packed / sent out -> no auto; Needs you "🚫 wants to cancel
  a paid order" with Cancel order (note, send "order cancelled" or nothing; refund outside the system)
  or "keep order". With a product name it is still `remove`.
- 6.5 Reports (/reports/wanted): "We don't have it" items grouped by name + asks for sizes that are out
  of stock now; times asked, customers, last asked; most asked first.
- Chat cart panel links to the customer's paid order on its way. Settings has the new templates.
- Test fix: tests/test_web.py fixture messages were dated 2026-10-10 and had aged out of the 3-day
  Needs-you window (test_auto failed before any change). They are now "30 days ago" (date-proof).
- Verified: pytest 223 passed, 1 skipped (new tests/test_after_payment.py: A1-A6 + parser cases).
  Live: services restarted (tunnel untouched), parser rules-3 re-parsed 19 messages, /healthz all ok.

## 2026-10-15 — v3 Step 7: FAQ auto-answers
- Migration db0641e10ac5 (after backup product_requests_2026-10-15T1722Z.dump, round-trip done):
  `faq_entries` (title, keywords, answer, active, edited, sort_order) seeded with the 4 spec entries
  (shown "edit me" until saved once); outbox kind + quick kind `faq`.
- Settings > 💬 FAQ answers: edit title / keywords (comma separated) / answer / active, delete, add.
  Matching reads the table every time, so edits work at once.
- Matching (app/replies/faq.py): normalized text; Latin keywords must stand alone ("cod" not in
  "code"), Burmese keywords are substrings; most keywords found wins (tie: first in the list).
  Only when the message names no product and no size: intent other/unknown -> the FAQ answer first;
  price / stock / delivery questions only when the normal flow has nothing (e.g. "kpay ရလား",
  where "kpay" is part of the keyword, not an unknown product: it no longer lands in "unknown items").
- Auto ON: sent like other auto replies (same speed, safety rules, 🤖, handled feed). Auto OFF:
  one-tap "💬 Send FAQ: {title}" on the message / inbox row, and on its "unanswered" row in Needs you
  (the inbox hides intent "other" by default). Every FAQ answer is marked 🤖 in the chat.
- Product named + FAQ question ("sauvage edp 10ml ဘယ်လောက်လဲ original လား"): the price reply goes out,
  and Needs you shows "also asks: FAQ “Authentic”" with Send FAQ / done (24 h).
- Unmatched questions: no reply, Needs you "unanswered" (Step 6.3).
- Test A4 (Step 6) uses "authentic လား" as an unanswerable question; it now switches the FAQ off
  inside that test, since B1 requires the FAQ to answer exactly that text.
- Verified: pytest 232 passed, 1 skipped (new tests/test_faq.py: B1 auto ON / auto OFF one-tap,
  B2 + "kpay ရလား", most keywords wins, B3, B4 + hint + send, B5 edit / add in Settings, B6).
  Live: restarted, /healthz all ok. NOTE: live auto-reply is ON, so from now on FAQ questions get
  the seed answers automatically — edit them in Settings if the wording should change.

## 2026-10-15 — v3 Step 8: daily sales & profit
- Migration 53fdc749b259 (after backup product_requests_2026-10-15T1731Z.dump, round-trip done):
  `product_costs` (bottle cost history, append-only like prices), `order_items.unit_cost_mmk`.
- Price list Excel: optional `bottle_cost` column (last column in the export; empty = unchanged; preview
  shows "bottle cost: 300,000 → 320,000"). Settings > 🧪 Vial cost per decant size (default 0).
- Cost of an item = bottle_cost / bottle ml × size + vial cost of that size (full bottle = bottle_cost),
  stamped on the order items when the payment is approved (cost at the time of sale; later price or cost
  changes don't touch old sales). Unknown cost (no bottle_cost / no bottle size) -> "—".
- Sales page (/sales, nav "Sales"): Today / Yesterday / This week (from Monday) / This month / custom
  dates, Yangon days, paid orders only (paid, packed, sent out, delivered; by paid_at; cancelled after
  payment = not counted). Tiles: revenue, orders, items, ml, cost, profit, profit %, average order.
  Bar chart per day (inline SVG, hover a bar for the day's total). Tables per day, per perfume (by
  revenue), per size. Any item without cost -> cost / profit "—" + note "add bottle_cost in the price
  list", and a button "Use today's costs for N order(s) already paid" (for sales made before the
  costs were entered). "⬇ Export .xlsx" = the same numbers (Summary, Per day, Per perfume, Per size).
- Verified: pytest 239 passed, 1 skipped (new tests/test_sales.py: C1 paid only + Yangon midnight
  boundary, C2 15,500, C3 price and cost changed after the sale, C4 "—" + fill costs, C5 export =
  page tiles, Excel bottle_cost round trip, cost math). Live: restarted, /healthz all ok.
- Owner to do (optional): add `bottle_cost` to the price list Excel and the vial costs in Settings,
  so profit shows. No paid orders exist yet, so nothing needs filling.

## OWNER TEST SCRIPT (v3: Steps 6-8)
Setup: open the dashboard (address: `bash scripts/status.sh`). Header must say "🤖 Auto-reply: ON".
Use a SECOND Telegram account (not ignored, not "Never auto-reply"). Each automatic reply arrives
~3 s after your message. The first reply of the day starts with "မင်္ဂလာပါ။" (6 h rule) — below it is
left out. If your test account already has a saved phone + address, the cart list ends with
"ဖုန်း …၊ လိပ်စာ … ကိုပဲ ပို့ပေးရမလား။" instead of asking for the phone: answer "ဟုတ်ကဲ့" and skip to 5.
Optional first: Prices > download Excel, fill `bottle_cost` for Good Girl (e.g. 240000; its bottle is 80 ml), upload,
Confirm; Settings > Vial cost: 5ml = 500. Then step 9 shows a profit.

A. FAQ (Step 7)
1. Send `authentic လား` -> "အားလုံး authentic (original) ပစ္စည်းတွေ ကနေ ခွဲထည့်ပေးတာပါနော်။" (🤖 in the chat).
2. Send `ဘယ်နှစ်ရက်ကြာလဲ` -> "ရန်ကုန်မြို့တွင်း ၁-၂ ရက်၊ နယ်ကို ၃-၅ ရက်လောက် ကြာပါတယ်နော်။"
3. Send `kpay ရလား` -> "KPay / AYA Pay နဲ့ ကြိုလွှဲပေးရပါတယ်။ ပို့ခကိုတော့ ပစ္စည်းရောက်မှ ပေးရပါတယ်နော်။"
4. Send `ဒီအနံ့က ဘယ်လိုမျိုးလဲ` -> NO reply. After 2 min the Inbox "🟡 Needs you" shows
   "💬 <you>: ဒီအနံ့က ဘယ်လိုမျိုးလဲ · unanswered". Tap "done" -> it disappears.
5. Settings > 💬 FAQ answers: change one answer, Save ("edit me" disappears); send its keyword again
   -> the new answer.

B. Order to delivery (Step 6)
1. Send `good girl 5ml ယူမယ်` -> "• Good Girl 5ml – 21,000 ကျပ်\nစုစုပေါင်း 21,000 ကျပ်ပါ။\n
   ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"
2. Send a phone, e.g. `09777123456` -> "ဖုန်းနံပါတ် 09777123456 ရပါပြီ။ ပို့ပေးရမယ့် လိပ်စာ ပို့ပေးပါနော်။"
3. Send `No. 12, Bahan` -> payment info: item line, "စုစုပေါင်း 21,000 ကျပ်ပါ။", the KPay and AYA Pay
   lines, "ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။"
4. Send ONE photo (any screenshot). Dashboard: "Payments 1". Open it, wait for the picture, type any
   transaction ID (e.g. TEST1), ✅ Approve (amount = 21,000). -> after 10 s: "✅ Order #100x
   အတည်ပြုပြီးပါပြီ။ …". Orders (nav) shows a badge 1, tab "📦 To pack".
5. Send `ဘယ်တော့ရောက်မလဲ` -> "Order #100x ကို ပြင်ဆင်နေပါတယ်။ ပို့လိုက်တာနဲ့ အကြောင်းကြားပေးပါမယ်နော်။"
6. Orders > 📦 Packed. Then tap "↩ Undo packed" -> back in To pack. Tap 📦 Packed again.
7. Send `အော်ဒါ cancel` -> NO reply (the order is paid). Needs you: "🚫 <you>: wants to cancel a paid
   order #100x". Tap "keep order (done)" (do NOT cancel, so the test can go on).
8. Orders > tab 🚚 To send > "🚚 Sent out", fill Deli name `Ko Min`, Deli phone `09555111222`, tap
   "Sent out + tell the customer". After 60 s: "Order #100x ကို ပို့လိုက်ပါပြီ။\nDeli: Ko Min
   09555111222\nပို့ခကို ပစ္စည်းရောက်မှ ပေးချေပေးပါနော်။" (Undo within those 60 s = no message.)
9. Send `ရောက်ပြီလား` -> "Order #100x ကို <today dd/mm/yyyy> မှာ ပို့ပြီးပါပြီ။\nDeli: Ko Min 09555111222"
10. Orders > tab Sent > ✅ Delivered -> NO message (thank-you is off in Settings > 📦 Orders & payments).
11. Sales (nav) > Today: revenue 21,000, 1 order, 1 item, 5 ml. With the optional costs:
    cost 15,500 (240,000 / 80 ml × 5 ml = 15,000 + 500 vial), profit 5,500, 26.2 %. Without costs:
    cost / profit "—" + the note. ⬇ Export .xlsx: same totals.

C. Cancel / remove (Step 6.4)
1. Send `sauvage edp 5ml, ysl y 5ml ယူမယ်` -> list with both, total 38,000.
2. Send `ysl y မယူတော့ဘူး` -> list with only Sauvage Eau de Parfum 5ml, total 20,000.
3. Send `မယူတော့ဘူး` -> "အော်ဒါ cancel လုပ်ပြီးပါပြီ။ နောက်မှ ပြန်မှာချင်ရင် ပြောပေးပါနော်။"
4. Send `ဘယ်တော့ရောက်မလဲ` -> NO reply (no paid order on its way; the delivered one doesn't count) ->
   after 2 min in Needs you as unanswered. Tap "done".

D. Not stocked + report (Step 6.5)
1. Send `hawas ice 10ml ဘယ်လောက်လဲ` -> NO reply; Needs you "❓ hawas ice". Open it, "We don't have it"
   -> "hawas ice ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။"
2. Reports (nav) -> "hawas ice · not in list · 1 · 1".

E. Payment reminder + auto-cancel (Step 6.2; optional, takes 2 h)
1. Settings > 📦 Orders & payments: reminder 1 h, cancel 2 h, Save.
2. Send `bdc 5ml ယူမယ်`, then `ဟုတ်ကဲ့` (or phone/address as asked) until you get the payment info. Send
   no photo.
3. After 1 h: "Order အတွက် ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။ စုစုပေါင်း 23,000 ကျပ်ပါ။"
   (only once). After 2 h: "ငွေလွှဲမှု မရရှိသေးတဲ့အတွက် အော်ဒါကို cancel လုပ်ထားပါတယ်။ ပြန်မှာချင်ရင်
   ပြောပေးပါနော်။" and Needs you shows "ℹ️ order cancelled automatically (not paid)".
4. Set the settings back to 12 h / 48 h.

If something differs: note the step number and what arrived; the chat page and Inbox show what the
system decided (🤖 = automatic).


## 2026-10-15 — v4 4.1: partial name matches (the "hawas for him" bug)
- Spec: docs/SPEC-v4.md 4.1. Parser is now `rules-4`.
- What: if a known nickname sits inside a longer name ("hawas for him" with the alias "hawas"),
  the item is NOT that product. It becomes ONE item with match `partial`, unknown text = the
  whole name, and the nickname's product kept only as a suggestion
  (`parse_items.candidate_product_id`). There is no one-tap button and no auto reply. The whole
  message waits in Needs you, and the product question lists the candidate first and preselected
  ("Contains the nickname of Hawas Ice, plus other words").
- Decisions: "extra words" = Latin words directly next to the alias (same comma part, stops at
  sizes, digits, Burmese text). These don't count as extra: filler/greeting words (hi, pls, for,
  edp...) and words of the product's own brand, name or same-brand aliases. So "dior sauvage
  elixir 5ml" is still Sauvage Elixir and "hi swy 5ml" is still Stronger With You.
- DB: migration 92fe0f25b1bf (parse_items.candidate_product_id), applied live after backup
  product_requests_2026-10-15T1925Z.dump; round-trip (down/up) done. The worker re-parsed 23 live
  messages with rules-4; nothing was sent because of it.
- Tests: tests/test_v4_partial.py (A1 partial → no reply, in Needs you, candidate first; A2 "hawas ice
  10ml" / "hawas 10ml" exact; A3 "good girl 5ml, hawas for him 10ml" → nothing sent, after the admin
  answers one reply with both and never "hawas him"; not-stocked variant). Fixture
  synthetic_messages.csv +3 rows (s56-s58: two partials, one brand-word check), all rows pass.
  Full suite: 246 passed, 1 skipped.

## 2026-10-15 — v4 4.2: teaching cards (the app learns from the admin)
- Spec: docs/SPEC-v4.md 4.2. Parser is now `rules-5`.
- **Teaching card** (message page, and inline in Needs you as "📘 သင်ပေးမယ်"). It appears for any
  message the app can't handle: unknown, partial, fuzzy or guessed names, no product named, an
  unclear intent, or a buy without a size. Burmese questions with big buttons, most likely answer
  first, at most 3 questions:
  - Q-product: top 3, 🔍 all products, ➕ new product, 🚫 we don't sell it.
  - Q-intent: buy / price / in stock / remove / cancel order / delivery / greeting / question (opens
    the chat to reply) / ignore.
  - Q-size: the sizes sold + full bottle.
  The learn box is ticked by default, and the words to learn are shown and editable. Next shows a
  preview line ("Y Eau de Parfum 10ml ကို ခြင်းထဲထည့်ပြီး စာရင်းပို့မယ်။" + the exact reply + what
  will be learned), made by the same code and rolled back. ✅ saves a human parse result, then the
  normal one-tap code sends the reply (10 s Undo). Undo also removes the patterns, the resolutions
  and the human parse the card created.
- **learned_patterns** (nickname / intent_phrase / not_stocked; pending → approved / rejected):
  - Pending: understood, but only a one-tap button marked "📘", never automatic.
  - Accepting a pending suggestion unchanged = +1 use. Changing it (card or "Correct the parse") = +1 correction.
  - A pattern is approved by the owner, or automatically after `auto_approve_after` uses (default 3;
    0 = owner only) with 0 corrections. Approved = like a seed alias / keyword.
  - Conflicts are never saved: e.g. a nickname that already belongs to another product. The owner
    decides on the Learning page ("Use the new answer" / "Keep it").
- **Greeting**: a message that is only a greeting (hi, hello, ဟယ်လို, ဟိုင်း, မင်္ဂလာပါ, mingalarpar …)
  is answered with the new template `greeting_reply` "မင်္ဂလာပါ။ ဘာကူညီပေးရမလဲ။". It isn't sent if
  we messaged them in the last 6 h. Can be switched off.
- **Not-stocked memory**: an approved not_stocked name gets the "we don't have it" reply
  automatically (setting `auto_not_stocked`, default ON) and counts in Reports > Wanted.
- **Staff adds a new product** without a price. The message waits, and Needs you shows the owner
  "💲 <product>: price needed" with a price box. Save → the list goes out by itself.
- **Learning page** (/learning, nav badge = waiting count): waiting patterns grouped by kind, each
  with an example message, who taught it and uses/corrections, plus ✅ approve / ❌ reject / ✏️ edit.
  Also the approved list with remove, conflicts, "handled by learned patterns this week", and the
  learning settings. Needs you shows "📘 N patterns to approve" and conflicts.
- Decisions:
  - Learned phrases win over seed keywords (they are what the admin taught).
  - A greeting phrase only counts when the whole message is a greeting.
  - Q-intent learns its phrase only when the card asked it. That's why B1's "ရောယူပါမယ်" (already
    = buy) is not saved.
  - The old v2 "unknown item" routes still work, but the message page now shows the card instead.
  - An unanswered message keeps its v3 row in Needs you, with its card attached.
- DB: migration d16b1c96eac6 (learned_patterns, parse_results.learned_ids, parse_items.name_text,
  intent greeting, quick kinds greeting/teach, reply kind greeting). Applied live after backup
  product_requests_2026-10-15T1956Z.dump; round-trip done. The worker re-parsed 23 live messages
  (5 are now greetings); nothing was sent.
- Tests: tests/test_v4_teaching.py (B1-B8 plus: new intent phrase, a correction blocks
  auto-approval, reject, auto-not-stocked off, greeting off, ignore/question, owner new product,
  conflict "use new", size question + learn off, settings validation). Three older tests changed
  because v4 changed what they check:
  - fixture s29 "မင်္ဂလာပါ" is now `greeting`, not `other`.
  - test_after_payment A4 used "ဟိုင်း" as an unanswered question; now a real question.
  - test_auto checked the old "Save as alias" text on the message page; now it checks the card.
  Fixture +4 rows (s59-s62). Full suite: 271 passed, 1 skipped.

## 2026-10-15 — v4 4.3: "the previous one" (reorder from history)
- Spec: docs/SPEC-v4.md 4.3. Parser is now `rules-6`.
- New intent `previous_item`. Seed phrases: ဟိုနေ့ကဟာ, အရင်ကဟာ, အရင်ယူတဲ့ဟာ, ပြီးခဲ့တဲ့တစ်ခါကဟာ,
  အဲ့ဒါ, အဲ့ဟာ, same one, last time, same as before, plus phrases taught on a card
  (Q-intent "အရင်ကဟာ ပြန်ယူမယ်"). It only counts when no product is named and the message is not a
  price / stock / remove question. So "အဲ့ဒါ ဘယ်လောက်လဲ" stays a price question.
- Candidates (product+size, no duplicates, newest first): the last PAID order's items, the current
  or last cart, and products asked about with a size in the last 30 days, before this message.
  - 1 → added (quantity from the message: "၂ ခု" = 2), and the list says
    "{product} {size} (အရင်ယူထားတဲ့ဟာ) ဟုတ်တယ်နော်။ မဟုတ်ရင် ပြောပေးပါ။". Auto allowed.
  - 2-5 → template `choose_previous` (numbered) + a `choice_prompts` row (expires in 24 h). The
    next message "1", "၁", "1 နဲ့ 2", "1,2", "2 ခုလုံး", "အကုန်" (optionally "...ယူမယ်") becomes a buy
    of those items. Auto allowed, since they picked from our own list. Anything else is parsed
    normally. With more than 5, the newest 5 are offered.
  - 0 → no reply; a teaching card asks which product + size. The answer finishes the order.
- Undo of the numbered list deletes the prompt, so a later "1" is just "1".
- New templates (editable): `previous_item_line`, `choose_previous`.
- DB: migration 814861587f85 (choice_prompts, intent previous_item, quick kind choose_previous,
  reply kind choice). Applied live after backup product_requests_2026-10-15T2008Z.dump; round-trip
  done. 23 live messages were re-parsed with rules-6; nothing was sent.
- Tests: tests/test_v4_previous.py (C1 auto add from a paid order; C2 numbered list, "2" and
  "၁"; C3 "1 နဲ့ 2" auto; C4 expired prompt → "1" is not a choice; C5 no history → card → order;
  C6 quantity 2; undo removes the prompt; parse_choice cases). Fixture +4 rows (s63-s66).
  Full suite: 281 passed, 1 skipped.

## 2026-10-15 — v4 4.4: roles, permissions, owner approval
- Spec: docs/SPEC-v4.md 4.4.
- **Owner only** (the link is hidden and the server answers 403 "Only the owner can do this."):
  - prices and the Excel import/export;
  - product add / activate / alias edits (staff see products read-only);
  - all of Settings: payment methods, templates, FAQ, order rules, vial costs, auto speed, learning settings;
  - the auto-reply switch (staff only see ON/OFF);
  - Users, Activity, the Learning page (approve / reject / edit / conflicts), and "price needed" pricing;
  - "Use today's costs" on Sales;
  - the old v2 "it's in my list" / "new product" routes.
- **Staff**:
  - Can use the inbox, Needs you, chats, replies, teaching cards, carts, order statuses, reports and Sales.
  - Sales and its export show revenue and orders only, with no cost or profit.
  - Payment decisions (approve / reject / not a payment / ask for one) follow the new switch "Staff may
    approve / reject payment screenshots" on the Users page (default ON). When it's OFF they get 403,
    and the payment card says the owner checks payments.
  - A nickname a staff member teaches (card, or "Save as alias" in Correct the parse) waits as a
    pending pattern for the owner, instead of becoming an alias at once.
  - "📘 N patterns to approve" and conflicts show only for the owner.
- **Users page** (/users): add a user (staff default, Burmese), reset password, disable / enable (you
  can't disable yourself), language. `scripts/create_user.py NAME --role staff` also works and starts
  staff in Burmese. A disabled user can't log in, and an open session ends at their next click.
- **Activity page** (/activity): the audit log with the user's name (or 🤖 auto), filter by person.
  Actions that had no audit entry now write one: product edits, review done/ignored, ignore customer,
  parse correction, Needs-you clear.
- DB: migration 222274ae7a9b (users.disabled, users.language; existing staff set to Burmese).
  Applied live after backup product_requests_2026-10-15T2033Z.dump; round-trip done. Live has one
  user (owner "admin"); no staff yet.
- Decision: a generic "log every POST" middleware was tried and dropped. It added noise (login,
  previews, double taps) and broke 4 audit tests. Explicit entries per action match the codebase.
- Tests: tests/test_v4_roles.py (D1 every owner-only GET/POST → 403 for staff and no menu links,
  staff pages that work; staff sales without cost/profit incl. export; D2 payments switch ON/OFF;
  D3 staff-taught pattern → owner approve → parser uses it → reject → ignored; staff alias waits;
  D4 auto_approve_after=0 keeps it pending after 5 uses; D5 disabled login + open session; users
  page + activity names; create_user script). Full suite: 290 passed, 1 skipped.

## 2026-10-16 — v4 4.5: Burmese dashboard, help, practice mode, staff guide
- Spec: docs/SPEC-v4.md 4.5. No migration (users.language came with 4.4).
- **Two languages, per user.**
  - Every page, button, menu, status name, empty state, error page and flash note now comes from one
    translation table: `app/web/i18n.py` (helpers) and `app/web/i18n_my.py` (about 800 Burmese texts).
  - Templates use `t("English text")` for fixed words, `tr(value)` for texts made in Python (button labels,
    notes, errors) and `code(value)` for intents and statuses.
  - Texts made in Python with numbers or names in them ("Order #1001: 📦 Packed. Undo for 60 s.") are matched
    by pattern, sentence by sentence. Unknown text (customer words, product names) is never changed.
  - Staff start in Burmese. The owner account stays English until you switch it.
  - **🌐 in the header** switches your own language. It is saved on your user, so it stays after you log out
    and log in again. The login page uses the language of whoever logged out last (Burmese for a new browser).
- **"?" help**: a small ? next to each main section (Needs you, inbox filters, teaching card, quick reply,
  correct the parse, cart, chat reply, chats, payments, payment approve, orders, products, sales, wanted,
  practice). Tap it to see one Burmese sentence.
- **❓ Help page** (`/help`, everyone logged in) shows `docs/STAFF-GUIDE-my.md`. Sections:
  - what each screen is;
  - "a message came — what do I do?" and the cart steps;
  - teaching cards;
  - checking payments (open the KPay app, find the transaction, type its ID);
  - packed → sent → delivered;
  - what NOT to do;
  - who to ask;
  - practice.
  The guide is plain Markdown, so you can edit it on GitHub.
- **🎓 Practice** (`/practice`, everyone):
  - Uses the one-item rows of `tests/fixtures/synthetic_messages.csv` whose product exists in today's catalog,
    plus 4 v4 examples ("ysl edp", "လေးထည့်ထားပေး", "liquid brun" = we don't sell it, "လည်း ယူမယ်").
  - Each message goes through the real parser, the real teaching card or one-tap button, and the real reply.
  - On a one-tap message the trainee either taps the button or presses "❌ This is wrong — don't send". Tapping
    is right only when the app understood the message correctly.
  - The result shows ✅/❌, the right answer, the reply the customer would have got, and a running score.
  - Nothing is saved: each step runs in one database transaction that is always rolled back (the code's own
    commits only close savepoints). The listener and worker never see it, so nothing is sent. The score lives
    in the browser session.
- **Errors** (403/404/…) are now a small page in your language, not raw JSON. HTMX requests still get plain text.
- Decisions:
  - The teaching card stays Burmese for both languages. It was Burmese-first in 4.2, and the tests check its
    exact words. The Q-intent button "အော်ဒါ cancel" is now "အော်ဒါ ပယ်ဖျက်", so the Burmese UI has no
    English word.
  - Loan words kept: ml, ကျပ်, KPay/AYA, FAQ, ID, Telegram, Excel, screenshot, size (card question), App.
  - Customer-facing reply templates were NOT changed (that is shop content, editable in Settings).
  - Activity in Burmese shows a Burmese group ("ငွေစစ် · payment.approve"). English shows the code as before.
  - Login errors in Burmese also show the English text in brackets, because the login page doesn't know who
    you are yet.
- Tests: `tests/test_v4_i18n.py`:
  - E1: owner and staff in Burmese open 28 pages plus 6 pages reached by POST (card preview, practice result,
    price preview, error page, login after logout, fresh login). All of them have data: a card, a one-tap
    reply, a cart, a payment to check, a paid order, a learned pattern, an unanswered question. The test scans
    the visible text, titles, placeholders, aria-labels and alt texts for about 150 English UI words. Product
    names, brands, customer texts and shop data are removed before the scan.
  - E1b: every t("…") in the templates has a Burmese entry, and so do all intents, statuses and Python-made labels.
  - E1c: pattern translation, and values are escaped.
  - E2: practice changes the row count of no table, nothing ends up in the outbox, no practice customer is
    left, and the score counts right and wrong answers.
  - E2b: exercises follow the catalog.
  - E3: the help page shows the guide, needs a login, and the renderer escapes HTML.
  - E4: the switch is saved per user, survives a new login, and doesn't change the owner's language.
  Full suite: 297 passed, 1 skipped (was 290 + 7 new). Fixture rows all pass (no regression).
- Deployed: backup product_requests_2026-10-16T0348Z.dump, web + parser restarted, /healthz ok, status.sh ok.

## OWNER TEST SCRIPT v4 (epics 4.1-4.5)
**Setup**
- Find the dashboard address with `bash scripts/status.sh`. Log in as admin. The header must show
  "🤖 Auto-reply: ON".
- Use a SECOND Telegram account.
- Before you start, open Chats > that account. If it has an open cart, tap "Cancel cart" at the bottom of the cart.
- Each automatic reply arrives ~3 s after your message. A one-tap or teaching-card reply arrives 10 s after ✅.
- The first reply after 6 quiet hours starts with "မင်္ဂလာပါ။" on its own line. It is left out below.

**A. Greeting (4.2). Do this first, while the account had no message from us for 6 h.**
1. Send `hi`. Expect "မင်္ဂလာပါ။ ဘာကူညီပေးရမလဲ။" (🤖 in the chat).
2. Send `hi` again. Expect no reply (we wrote less than 6 h ago).
3. Send `hi stw intensely 5ml ဘယ်လောက်လဲ`. Expect "Stronger With You Intensely 5ml က 18,000 ကျပ်ပါ။
   မှာယူချင်ရင် ပြောပေးပါနော်။" (not just a greeting, so it is answered as a price question).

**B. Partial names (4.1)**
1. Send `hawas for him 10ml ယူမယ်`. Expect NO reply.
2. Inbox > 🟡 Needs you shows "📘 <you>: hawas for him 10ml ယူမယ်" with "❓ hawas for him".
3. Open "📘 သင်ပေးမယ်". The first choice is Hawas Ice, with the line "“Hawas Ice” ရဲ့ nickname ပါပေမယ့်…".
4. Choose "🚫 ဒီပစ္စည်း မရှိဘူး", then "ဆက်လုပ်မယ် →". The preview says "မရှိဘူးလို့ ပြန်ပြောမယ်။".
5. Press ✅. Expect "hawas for him ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။".
6. Send `hawas 10ml ယူမယ်`. Expect an automatic list:
   "• Hawas Ice 10ml – 20,000 ကျပ်\nစုစုပေါင်း 20,000 ကျပ်ပါ။\nဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"
7. Chats > your account > "Cancel cart".

**C. Teaching cards and learning (4.2)**
1. Send `ysl edp 10 ml ရောယူပါမယ်`. Expect NO reply. Open its 📘 card: the first choice is Y Eau de Parfum.
   The learn box is ticked and shows "ysl edp".
2. Press "ဆက်လုပ်မယ် →". The preview says "Y Eau de Parfum 10ml ကို ခြင်းထဲထည့်ပြီး စာရင်းပို့မယ်။" and
   "📘 “ysl edp” = Y Eau de Parfum". Press ✅. Expect
   "• Y Eau de Parfum 10ml – 34,000 ကျပ်\nစုစုပေါင်း 34,000 ကျပ်ပါ။\nဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။".
3. Open Learning (nav badge 2). Nicknames shows "ysl edp" → Y Eau de Parfum, and "We don't sell" shows
   "hawas for him", both "taught by admin". Press ✅ Approve on both.
4. Cancel the cart again. Send `ysl edp 5ml ယူမယ်`. Expect an AUTOMATIC list with Y Eau de Parfum 5ml –
   18,000 (the nickname is approved now).
5. Send `liquid brun 5ml ရှိလား`. Expect NO reply. Card > "🚫 ဒီပစ္စည်း မရှိဘူး" > ဆက်လုပ်မယ် > ✅. Expect
   "liquid brun ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။".
6. Learning > approve "liquid brun". Send `liquid brun ရှိလား`. Expect the same reply, automatically.
   Reports (Wanted) shows liquid brun, asked 2 times.
7. Undo test:
   - Send `stw intensely 5ml လေးထည့်ထားပေး`. The card asks "ဖောက်သည်က ဘာလုပ်ချင်တာလဲ?". Choose ဝယ်မယ်,
     then ဆက်လုပ်မယ်, then ✅.
   - Within 10 s, press Undo on that message in the Inbox.
   - Expect: nothing arrives, and Learning shows no "လေးထည့်ထားပေး".

**D. "The previous one" (4.3)** (needs a paid order or a cart from before; step C left one)
1. Send `ဟိုနေ့ကဟာ ထပ်ယူမယ်`. You get one of these:
   - one earlier item: the list plus "<product> <size> (အရင်ယူထားတဲ့ဟာ) ဟုတ်တယ်နော်။ မဟုတ်ရင် ပြောပေးပါ။";
   - several: "အရင်က ယူထားတာတွေပါ –\n1. …\n2. …\nဘယ်ဟာလဲ နံပါတ်လေး ပြောပေးပါနော်။".
2. If you got the numbered list, send `၁`. Item 1 is added and the list comes back.
3. Wait 25 h is not practical, so skip the expiry test (it is covered by test C4).

**E. Staff, permissions (4.4)**
1. Users > Add a user. Username `staff1`, a password of 10+ characters, role staff, language မြန်မာ.
2. In a private browser window, log in as staff1. Check:
   - the menu is Burmese and has no Prices / Learning / Settings / Users;
   - auto-reply shows ON but can't be clicked;
   - opening `<address>/settings` shows "ခွင့်မပြုပါ" and "ဒါကို ပိုင်ရှင်ပဲ လုပ်နိုင်တယ်။";
   - Sales (အရောင်း) shows ရောင်းရငွေ but no cost or profit.
3. From the test account send a misspelled name, e.g. `savage edp 10ml ယူမယ်`. As staff1, open its 📘 card,
   choose Sauvage Eau de Parfum and press ✅. In your owner window, Learning shows the nickname "taught by staff1",
   waiting for approval.
4. Users > "What staff may do": untick payments, Save. staff1 opening a payment sees
   "ငွေစစ်တာကို ပိုင်ရှင်က လုပ်ပါမယ်" and no Approve button. Tick it again.
5. Users > Activity: staff1's actions are listed with their name.

**F. Burmese dashboard, help, practice (4.5)**
1. As staff1, every page is Burmese.
   - Tap a "?" next to a section: one Burmese sentence appears.
   - Tap "🌐 English": the page is English. Log out and in again: still English.
   - Tap "🌐 မြန်မာ" to go back.
2. "❓ အကူအညီ" shows the staff guide with a contents list.
3. "🎓 လေ့ကျင့်ခန်း" > "စမယ် →". Answer 3-4 messages, tapping the button or answering the card. Each answer
   shows ✅ or ❌, the right answer, and the reply the customer would have got. The score goes up.
4. Check that nothing was saved or sent:
   - your test Telegram account received nothing;
   - Chats has no "🎓 လေ့ကျင့်ခန်း ဖောက်သည်";
   - the Inbox has no new practice message.
5. As owner, tap "🌐 မြန်မာ" in the header: your own dashboard turns Burmese, and staff1 is unaffected. Switch
   back with "🌐 English".
6. Users > staff1 > Disable. staff1's next click goes to the login page, and logging in fails.

## STAFF TEST (ဝန်ထမ်း စမ်းသပ်ချက် — ပိုင်ရှင် ဘေးကကြည့်ပြီး ၁ နာရီ)
ပိုင်ရှင်က ဝန်ထမ်းအကောင့် ဖွင့်ပေးပါ (Users > Add a user၊ ဘာသာ မြန်မာ)။ ဝန်ထမ်းက ဖုန်းနဲ့ လုပ်ပါ။
1. Dashboard လိပ်စာကိုဖွင့်ပြီး ကိုယ့်နာမည်၊ စကားဝှက်နဲ့ **ဝင်မယ်**။ Menu အားလုံး မြန်မာလို ဖြစ်ရမယ်။
2. **❓ အကူအညီ** ကိုဖွင့်ပြီး လမ်းညွှန်ကို ဖတ်ပါ (၁၅ မိနစ်)။
3. **🎓 လေ့ကျင့်ခန်း → စမယ်**။ စာအားလုံး ဖြေပါ။ **အမှတ် ၈၀% အထက်** ရရမယ်။ မရရင် နောက်တစ်ခေါက် ထပ်လုပ်ပါ။
4. ပိုင်ရှင်က တခြား Telegram အကောင့်ကနေ ဒီစာတွေ ပို့မယ်။ ဝန်ထမ်းက တစ်ယောက်တည်း ဖြေပါ:
   - `good girl 5ml ဘယ်လောက်လဲ` → App ဖြေပြီးသား ဖြစ်ရမယ် (🤖)၊ မဖြေရသေးရင် **💬 ဈေး ပြန်ပြောမယ်** ကို ဖတ်ပြီး နှိပ်။
   - `ysl edp 10 ml ရောယူပါမယ်` → **📘 သင်ပေးမယ်** → Y Eau de Parfum ရွေး → ဆက်လုပ်မယ် → ✅။
   - `ဒီအနံ့က ဘယ်လိုမျိုးလဲ` → **စကားပြော ဖွင့်ပြီး** ကိုယ်တိုင် ဖြေ။
   - ဖုန်းနံပါတ်နဲ့ လိပ်စာ ပို့ → ခြင်းထဲ **နောက်တစ်ဆင့်** ခလုတ်အတိုင်း လုပ် → ငွေလွှဲ အချက်အလက် ပို့။
   - Screenshot တစ်ပုံ ပို့ → **ငွေစစ်ရန်** → ပိုင်ရှင်ရဲ့ KPay မှာ စစ်တဲ့ပုံ လုပ်ပြ → ID ရိုက် → ✅ အတည်ပြုမယ်။
   - **အော်ဒါများ** → 📦 ထုပ်ပြီး → 🚚 ပို့လိုက်ပြီ → ✅ ရောက်ပြီ။
   - တစ်ခုကို မှားနှိပ်ပြီး **↩ ပြန်ဖျက်** နဲ့ ပြန်ဖျက်ပြ။
5. ပိုင်ရှင်က မေးမယ်: "ငွေမရောက်ဘဲ screenshot ပဲ ပို့ရင် ဘာလုပ်မလဲ?"၊ "ဈေးမသိရင်?"၊ "ဖောက်သည် ဒေါသထွက်ရင်?"
   → လမ်းညွှန်ထဲက **❗ မလုပ်ရမယ့်အရာများ** နဲ့ **🙋 မသိရင် ဘယ်သူ့ကို မေးမလဲ** အတိုင်း ဖြေနိုင်ရမယ်။
6. **အောင်မြင်တယ်** ဆိုတာ: ပိုင်ရှင် မကူဘဲ အပေါ်က ၁-၅ အကုန် လုပ်နိုင်တာ၊ ဖောက်သည်ဆီ စာမှား မရောက်တာ။

## 2026-10-16 — v4.6: AI helper (OpenAI) with an evaluation gate (docs/SPEC-v4.6-ai.md)
**S0 key check:** OK. One tiny call to gpt-6-luna succeeded; the key was never printed.

**What was built**
- `app/ai/`: provider interface (`openai` = official SDK 3.31, Responses API, strict JSON schema, `store=false`,
  prompt-cache key; `fake` for tests), privacy masking, prompt (static instructions + product list with ids,
  nicknames, sizes sold and bottle size, approved "we don't sell" words and FAQ titles FIRST, then the masked
  message, the last 10 chat messages, the cart and the last paid order), checker, service (when to call,
  caps, AUTO), hints (SHADOW card), report (AI page numbers and notices).
- `ai_calls` table (tokens, cached tokens, cost, latency, ok, error kind, checked result, decision) and
  `learned_patterns.via_ai`. Migration e29f24a992e0; down/up round trip tested.
- Parser worker: after the rules, an AI step for fresh (24 h) unsure messages only, then auto mode.
  "Unsure" = intent other/unknown without an FAQ, an unknown / partial / fuzzy / ambiguous / context item, a
  product question with no product, or previous_item with no history. Never: photos, rules-certain messages,
  approved learned patterns, pending 📘 patterns (they are already a one-tap suggestion), ignored customers,
  handled messages. At most one call per message; every call or skipped call is one ai_calls row.
- SHADOW (the default, deployed): the AI's answers are pre-selected on the 📘 teaching card ("🧠 AI suggests"
  + reason + %). If the AI's product is not among the card's options, it is added. not_in_list at ≥ 0.85 →
  "🚫 ဒီပစ္စည်း မရှိဘူး" pre-selected. If the AI's intent differs from the rules', the card asks "what do they
  want?" with the AI's answer pre-selected. Questions show the AI's Burmese draft in an editable box: ✅ sends
  it (admin click, 10 s Undo); it is never automatic. ✅ unchanged → ai_calls.decision = accepted; anything
  changed (also the draft) → corrected. Patterns from the card are pending, shown as "🧠 AI + <user>".
- AUTO (owner switch, OFF until the owner turns it on): checker OK + confidence ≥ threshold (0.85) + allowed
  intent + every item a product (buys need a size) or not_in_list ≥ 0.9; cancel_order only with an open
  cart; previous_item only if every item is in the customer's history. Then: parse result method="ai",
  not_in_list → unknown_requests "not_stocked" (Wanted report), learn entries → PENDING patterns (taught by
  "🧠 AI"), and the normal auto engine continues with all its safety rules. In AUTO mode the auto engine
  waits for the AI's answer on unsure messages. Otherwise → SHADOW behaviour. Re-parsing keeps AI results
  (like human ones). 🧠 in the chat on AI-understood messages (hover = reason).
- AI page `/ai` (owner): mode OFF / SHADOW / AUTO, today and this month (calls, cost, average time, accepted,
  corrected, accuracy, auto, errors / refused, not called, answered with learned patterns), settings (daily
  cap 300, monthly budget $5, threshold, model, reasoning), last 50 calls, "Run evaluation" + latest report.
- Needs you notices: key refused / no credit / country (from the newest call), ≥ 50% of the last 20 calls
  failed, daily cap reached, monthly budget used up.
- Errors: 8 s timeout; 1 retry on network errors only; 401/403/429/no credit/timeout → decision "error", no
  crash, the message stays in Needs you. Invalid JSON or any checker problem → "rejected".
- Staff guide: a short "🧠 AI အကြံပြုချက်" section. All new screens are translated into Burmese.

**Decisions**
- Live messages are masked before sending. Phones become [PHONE], house numbers / streets / wards become
  [ADDRESS], runs of 6+ digits become [NUMBER]. Sizes, quantities, prices up to 5 digits and township names
  stay. Photos become "[photo]". Our payment / contact replies become "[contact / payment details]".
  Customer names are never sent.
- Product ids and sizes are enums in the strict schema, so the model cannot even write an unknown id; the
  checker still checks everything (active, size sold, qty 1-20, learn text really in the message).
- One prompt rule was added after an evaluation run mapped "ysl 5ml" to Y EDP: a brand name alone is not a
  product when we sell more than one of that brand. It stays null unless the chat or cart shows which.
  Afterwards "ysl edp" is sometimes left for the person to pick (the safe direction).
- The worker remembers "no AI needed" per (message, parse result), so certain messages are not re-checked
  every second.
- The auto engine reads the AI mode once per pass (a per-message query made a timing test flaky).

**S2 evaluation gate (real API, tests/fixtures/ai_eval.csv: 48 cases, the owner's 10 examples, context,
not-in-list flankers, typos, Zawgyi, questions)** — PASS
| run (gpt-6-luna, reasoning low) | intent+products | wrong product ids | not_in_list mapped | sizes | cost | avg time |
|---|---|---|---|---|---|---|
| final (after the brand rule) | **100%** | **0** | **0** | 100% | $0.0041 | 1.9 s |
| 3 runs after the brand rule | 98-100% | 0 | 0 | 100% | ~$0.0045 each | 2.2-2.3 s |
| run before the brand rule | 98% | 1 ("ysl 5ml" → Y EDP) → FAIL | 0 | 100% | $0.0046 | 2.3 s |
- Prompt caching works: ~99% of input tokens were cached. One real call costs about $0.0001.
- One run had a single 8 s timeout. That case simply goes to Needs you, which is the designed fallback.
- Reports are in data/exports/ai_eval_*.json (git-ignored); the AI page shows the latest.

**Tests:** 332 passed, 1 skipped (was 297 + 1). 35 new tests in tests/test_v46_ai.py cover F1-F11 and the AI
page. F1: checker rejections → Needs you, nothing sent. F2: what leaves the server is masked; no photos, no
payment details. F3: cap, next day, budget. F4: every error kind + OpenAI SDK error mapping + store=false.
F5-F8: SHADOW / AUTO / not-in-list / questions. F9-F10: no calls when the rules are sure or a pattern is
approved. F11: cost. All tests use the fake provider (AI_PROVIDER=off in tests). The synthetic fixture has
no regressions. /ai is part of the "every page Burmese" test.

**Deployed:** backup product_requests_2026-10-16T1820Z.dump, migration at head, AI mode = SHADOW, parser +
web restarted, /healthz ok, scripts/status.sh ok. AUTO stays off until the owner switches it on at /ai.

## OWNER TEST SCRIPT v4.6 (AI helper)
Before you start: Chats > your test account > "Cancel cart", so the cart is empty. Auto-reply can stay as it
is for part A. Each AI answer takes 2-4 s, so wait about 5 s, then reload the Inbox. The 📘 card is in
"🟡 Needs you" and on the message page.

**A. SHADOW (as deployed).** Send these from the second Telegram account, one at a time:
1. `ysl edp 10 ml ရောယူပါမယ်` → card: "🧠 AI suggests · …ysl edp = Y Eau de Parfum…".
   - Y Eau de Parfum 🧠 is selected, and the learn box says "ysl edp".
   - Tap ဆက်လုပ်မယ် → ✅. Expect the cart list with "• Y Eau de Parfum 10ml – … ကျပ်".
2. `hawas for him 10ml ယူမယ်` → card: "🚫 ဒီပစ္စည်း မရှိဘူး 🧠" is selected. Tap ဆက်လုပ်မယ် → ✅. Expect
   "hawas for him ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။".
3. `Good girl 5ml, swy 10ml, liquid brun 10ml ယူပါမယ်` → the card asks only about "liquid brun", with 🚫 🧠
   selected. Tap ✅. Expect Good Girl 5ml + Stronger With You 10ml in the list, plus the "liquid brun …
   မရှိသေးပါဘူး" line.
4. `ဟိုနေ့ကဟာ ၂ခု ထပ်ယူမယ်` → no 🧠. The rules find it in your history: a one-tap button or the
   numbered "which one?" list, as in v4. The AI is only asked when there is no history.
5. `ဒီအနံ့က ဘယ်လိုမျိုးလဲ ညနေဘက်သုံးလို့ရလား` → in Needs you at once.
   - The card shows "မေးခွန်း — ကိုယ်တိုင်ဖြေမယ် 🧠" and a box with the AI's Burmese draft.
   - Read it and edit it (remove anything wrong).
   - ဆက်လုပ်မယ် shows "ဒီအဖြေကို ဖောက်သည်ဆီ ပို့မယ်။" and your text. ✅ sends exactly that text after 10 s
     (Undo possible). Nothing is ever sent without your ✅.
6. `stonger with u intense 5ml ဈေးဘယ်လောက်လဲ` → the rules guessed "Stronger With You" (wrong); the card shows
   Stronger With You Intensely 🧠 selected. ✅ → the price of Stronger With You **Intensely** 5ml.
7. `ysl ကို မယူတော့ဘူး` (Y EDP is in the cart from step 1) → card: Y Eau de Parfum 🧠. ✅ → Y EDP removed and
   the list sent again.
8. `ရန်ကင်း သုခလမ်း အမှတ်၁၂ ကိုပို့ပေးပါ ဖုန်း ၀၉၇၇၇၁၂၃၄၅၆` → no 🧠 (the rules know addresses). The phone /
   address buttons work as in v4.
9. `hi ဘာတွေရလဲ` → card: "နှုတ်ဆက်တာ 🧠" (or "မေးခွန်း 🧠" with a draft) is selected. Tap ✅ (or edit the draft).
10. `ဘလူးဒီချန်နယ် အပြည့်ဗူး ရှိလား` → no 🧠. The rules already know it (Bleu de Chanel, full bottle): a
    one-tap button, or an automatic answer if auto-reply is ON.
- To see a "corrected" answer: in step 6 or 7, choose a different product than the 🧠 one before ✅.
- Learning page: "ysl edp", "hawas for him", "liquid brun" … show "taught by 🧠 AI + owner", waiting for
  approval.

**B. AUTO (3 messages).** Cancel the cart. At /ai press "AUTO: acts when sure". The 🤖 Auto-reply in the header
must be ON. Use new words, because the words taught in part A are now learned patterns: the rules handle
those without the AI (no AI call, no cost).
1. `savage edp 10ml ယူမယ်` → automatic list with "• Sauvage Eau de Parfum 10ml – …", sent 2-3 s later.
   - Chats: your message has 🧠; hover shows the reason.
   - Learning: "savage edp" → Sauvage, "taught by 🧠 AI", waiting.
2. `dior homme intense 5ml ဈေးဘယ်လောက်လဲ` → automatic "dior homme intense ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။".
   Reports > Wanted lists it.
3. `ဒီအနံ့က ဘယ်လောက်ကြာကြာ မွှေးလဲ` → NOT answered automatically (questions never are). The card with the
   draft is in Needs you.
- Bonus: send `ysl edp 5ml ယူမယ်` → the 📘 one-tap button, with no AI call (the AI page count does not go
  up).
- At the end, switch /ai back to SHADOW, unless you want to keep AUTO.

**C. AI page numbers.** Open /ai.
- Today: about 9-12 AI calls.
- Cost: well under $0.01 (about $0.0001 per call).
- Average time: about 2-3 s.
- Accepted / corrected match what you did in A; accuracy = accepted ÷ (accepted + corrected).
- "Handled automatically by the AI" = 2. "Answered with learned patterns" counts the 📘 taps.
- The last 50 calls list shows each message's intent, products, 🧠 reason, cost and time.
- "▶ Run evaluation" runs the 48 test messages against the real AI (about 1 cent, about 2 minutes). Reload:
  expect "✅ Passed", intent + products 100% (at least 90% needed), wrong products 0.
- Limits test (optional): set "Calls per day" to 1 and send two unknown names. The second gets no 🧠, and Needs
  you shows "🧠 AI: daily limit of 1 calls reached…". Set it back to 300.

## 2026-10-17 — v4.7: SHADOW → AUTO graduation, safety brake, weekly AI summary (docs/SPEC-v4.7-graduation.md)
**What was built**
- `app/ai/graduation.py`: graduation, safety brake and the weekly summary.
  - Graduation is checked by the parser worker every day at 09:00 Asia/Yangon. Rules: SHADOW +
    auto-graduate ON + at least 7 days + at least 50 checked suggestions + accuracy ≥ 95% + 0 wrong
    products + errors < 10%. Then: AUTO, an audit row (actor "auto-graduation"), and the Needs you notice
    "🧠 AI switched to AUTO: accuracy X% on N decisions, 0 wrong products".
  - The brake is checked after every decided suggestion, after every AI step and daily. AUTO goes back to
    SHADOW when: a product of an AUTO-handled message is changed, OR accuracy of the last 30 decided
    results is < 90%, OR ≥ 50% of the last 20 calls failed. The notice gives the reason, and the window
    restarts at the brake time.
- `ai_calls.decided_at` and `ai_calls.wrong_product` (migration c409d2aafcbe; down/up tested; old decided
  rows get decided_at = created_at).
- "🧠 AI was wrong" on the message page of an AUTO-handled message: a card-style form (product per line or
  "we don't sell it", size, quantity, what the customer wanted). Saving it stores a human parse result,
  counts the call as corrected (wrong product if a product changed), counts corrections on the AI's pending
  patterns from that message, runs the brake, and opens the chat to fix the cart or reply (Undo works while
  the reply waits). Editing an AUTO AI result with the existing "edit parse" form counts the same way.
- /ai: the "🎓 Graduation progress" section shows days, checked suggestions, accuracy, wrong products and
  errors, each ✅ / ⏳ / ❌, with what is missing. New settings: auto-graduate, min days, min decisions,
  min accuracy. A manual mode switch turns auto-graduate OFF; the checkbox turns it on again.
- Weekly summary: from Monday 09:00 Yangon the worker writes reports/ai-weekly.md for the last full
  Monday-Sunday week (Yangon). It holds week, mode, calls, cost, average time, accepted, corrected, wrong
  products, accuracy, errors / refused, not called, AUTO-handled, AI patterns approved / pending, and
  graduation progress. It contains only numbers.
  - It is committed alone ("AI weekly summary", `git commit --only`; other staged files stay staged) and
    pushed with the deploy key.
  - If the branch has unpushed local commits, it is not pushed (a push would send them too).
  - A failed push is logged and the worker keeps going.
  - First run: the current week is only remembered; no summary is written for weeks before the deploy.

**Decisions**
- Wrong product = the AI named a product and the admin chose a different one, or "we don't sell it".
  The AI saying "we don't sell it" and the admin choosing a product is a normal correction (the safe
  direction). Changing only size, quantity or intent is a normal correction.
- For the brake's "last 30 decided results", an AUTO-handled result counts as right until someone presses
  "🧠 AI was wrong". Otherwise only the low-confidence SHADOW cards would count, and the brake would fire
  for no real reason.
- Window: the last 14 days, never before SHADOW (re)started. The window start is exclusive, so the
  correction that fires a brake belongs to the old window.
- The spec says "opens the teaching card". The 4.2 card is built from the rules' unsure items, which an
  AUTO message does not have, so "🧠 AI was wrong" opens a correction card with the same questions for
  every line the AI handled.
- The worker's tick touches the database only when something is due (not every second). git has a 60 s
  timeout, so a weekly push can pause the parser for at most a minute.

**Tests:** 351 passed, 1 skipped (was 332 + 1). 19 new tests in tests/test_v47_graduation.py:
- G1: graduation, notice, audit, once a day, only from 09:00.
- G2: each missing condition — 6 days / 40 decisions / 94% / 1 wrong product / 12% errors — stays SHADOW
  and the page shows what is missing; decisions older than 14 days don't count.
- G3: product correction on an AUTO message via "AI was wrong" and via the edit form; size-only correction
  doesn't brake; 87% on the last 30 brakes, 90% doesn't; 50% errors brakes; the brake runs after the AI
  step; the window restarts after a brake.
- G4: a manual switch turns auto-graduate off; turning it on again works.
- G5: the summary has none of the customer name, username, phone, address, message text or AI result
  texts used in the test, and no Burmese text at all; it covers the right week, is written once per week,
  and nothing is written for the past on the first run. publish() was tested against a throwaway local git
  remote: only the summary file is committed, staged work stays staged, unpushed local commits make it skip,
  and a failed push returns a message instead of raising.

**Deployed:** backup product_requests_2026-10-16T1903Z.dump, migration at head, AI mode = SHADOW,
auto-graduate ON, window since 2026-10-16 18:21 UTC (the 4.6 deploy), parser + web restarted, health ok.
git ls-remote works from the systemd user environment. Earliest possible graduation: 2026-10-24 09:00
Yangon, if 50 suggestions have been checked by then. First weekly summary: Monday 2026-10-19 09:00 Yangon
(week 2026-10-12 to 10-18).

**Owner test (short)**
1. /ai → "🎓 Graduation progress": days 0-1 / 7 ⏳, checked suggestions n / 50 ⏳, accuracy, wrong products 0 ✅,
   errors ✅. Auto-graduation: ON.
2. Keep answering 🧠 cards normally for 1-2 weeks. Change the product only when the AI is really wrong; that
   is what counts as a wrong product.
3. To try the brake safely now: press AUTO at /ai (auto-graduate turns OFF; the page says so). Send
   `savage edp 10ml ယူမယ်` from the test account; the AI handles it automatically (🧠 in the chat). Open the
   message → "🧠 AI was wrong" → choose another product → Save. Expect: the chat opens, Needs you shows
   "🧠 AI switched back to SHADOW: an admin changed the product of an AUTO-handled message", and /ai shows
   SHADOW. Then tick "Auto-graduate" in the settings and Save, so it can graduate by itself again.
4. Monday after 09:00: reports/ai-weekly.md on GitHub, commit "AI weekly summary", numbers only.

## 2026-10-17 — v4.8: changing address / phone (live bug fix, docs/SPEC-v4.8-change-info.md)
**The live bug, reproduced first.** Returning customer, cart list ending "…ကိုပဲ ပို့ပေးရမလား။" → reply
"လိပ်စာ ပြောင်းချင်ပါတယ်".
- The word လိပ်စာ made it intent=address, and the whole sentence counted as an address.
- That counted as agreement: the cart was confirmed and payment info went out.
- The order's AND the customer's saved address became the sentence "လိပ်စာ ပြောင်းချင်ပါတယ်" itself
  (worse than reported).

**What was built**
- Parser rules-7:
  - `change_info` from the seed phrases (address / phone / both / unclear), checked before "address".
  - An address needs real content (township, street, number, ward, landmark or a long text);
    "လိပ်စာ", "ပို့ပေးပါ", "address" alone are not an address and never an agreement.
  - "မဟုတ်ဘူး / no / မဟုတ်ပါ / ပြောင်းမယ်" right after the returning question → change_info (unclear).
  - `change_info` is learnable (teaching card choice "လိပ်စာ / ဖုန်း ပြောင်းချင်") and the AI may return it
    (prompt + schema + checker; AUTO allowed).
- Saving addresses: "ဒီလိပ်စာကိုပို့ပေးပါ - …" / "လိပ်စာအသစ် …" / "new address: …" prefixes are stripped, so only
  the address is saved.
- Change flow (new `orders.change_wanted`):
  - Reply ask_new_address / ask_new_phone / ask_new_contact (editable templates).
  - Payment info waits. Even "ok" meanwhile only repeats the question.
  - The next address replaces the order's and the customer's address; the next phone becomes the order's
    only phone and the customer's phone 1 (old ones kept below, max 3).
  - A phone without change words is still added. "ဒီလိပ်စာကိုပို့ပေးပါ …" / "this address" replaces
    without asking first.
- Replies after a change, by order status:
  - cart / confirmed: "လိပ်စာ ပြင်ပြီးပါပြီ – {address}" (phone_updated likewise), then payment info in the
    same message.
  - waiting_payment: that line only; payment info is never resent.
  - photo_received / paid / packed: saved + the line + Needs you "📍 Order #N address changed after payment —
    check before packing/sending" with a "✅ checked" button.
  - sent_out / delivered: no change, no reply; Needs you "customer wants to change the address of an order
    already sent".
- Dashboard:
  - The cart panel shows "📍 address changed at hh:mm (old: …)" for 24 h and "⏳ Waiting for the new address
    from the customer" as the next step.
  - The orders page has "Address / phone changes (n)" history (order_events kind "contact").
  - Undo of the tap restores the address, phones, waiting state, and removes the change event.
- Migration 45cb2f34b657: intent and quick-action checks, orders.change_wanted / change_asked_at,
  order_events.kind (status | contact | address_checked; status Undo only sees "status"). Down/up tested.
- Staff guide: a short "📍 လိပ်စာ / ဖုန်း ပြောင်းချင်ရင်" section; all new texts in Burmese.

**Decisions**
- Payment info itself still has no address line (unchanged template). "Payment info with the NEW address"
  = the "လိပ်စာ ပြင်ပြီးပါပြီ – <new address>" line comes first in the same message, and the order holds the
  new address. The order confirmation after payment uses the current order address (checked in H5).
- "AI said we don't stock it" etc. is unaffected. The AI eval set grew to 50 cases (a change request in
  new words; "လိပ်စာ" alone). Gate re-run after the prompt change: 100%, 0 wrong products (one earlier
  run had a single timeout on the new case; it was right 3/3 when repeated).

**Tests:** 387 passed, 1 skipped (was 351 + 1). 36 new tests in tests/test_v48_change_info.py:
- H1: the exact live case, by one-tap and in auto mode; Undo; "ok" while waiting.
- H2: "this address" replaces.
- H3: keywords alone are not an address and not agreement.
- H4: "no" to the returning question, then phone + address together; "no" without the question is not a
  change.
- H5: change after payment info, no resend; the confirmation shows the new address.
- H6: change after paid, with Needs you and "checked"; after sent out, Needs you only.
- H7: phone replace, then a plain number adds.
- H8: no AI call for rules-certain change messages; the card offers change_info; every seed phrase and
  every negative answer.
- The synthetic fixture and all earlier tests pass.

**Deployed:** backup product_requests_2026-10-16T1956Z.dump, migration at head, parser (rules-7) + web
restarted, health ok. Re-parse: 26 rows got the new version; 2 meanings changed:
- message 52 "ပို့ပေးပါ": address → other
- message 60 "လိပ်စာ ပြောင်းချင်ပါတယ်": address → change_info

**Live data the owner should look at (not changed by me):** order 28 (waiting_payment, customer 11) has the
address "လိပ်စာ ပြောင်းချင်ပါတယ်", and customer 11's saved address is the same. That is the bug's damage.
- Fix in the chat: ask the customer for the new address. When it arrives, the app saves it on the order
  and the customer.
- Or tell Claude Code to put order 28 into "waiting for the new address", so their next address is
  confirmed with "လိပ်စာ ပြင်ပြီးပါပြီ – …".

**Owner test (from a second Telegram account; Auto-reply ON)**
1. Make the account "returning": it needs a saved phone + address from an earlier order. Send
   `stw intensely 10ml ယူမယ်`. The list ends "ဖုန်း …၊ လိပ်စာ … ကိုပဲ ပို့ပေးရမလား။".
2. Send `လိပ်စာ ပြောင်းချင်ပါတယ်`.
   - Expect only "ပို့ပေးရမယ့် လိပ်စာအသစ် ပို့ပေးပါနော်။", NO payment info.
   - Chats > cart shows "⏳ Waiting for the new address from the customer".
3. Send `ok`. Expect the same question again, still no payment info.
4. Send `ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅`.
   - Expect "လိပ်စာ ပြင်ပြီးပါပြီ – ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် 5" + the payment info in one message.
   - The cart panel shows "📍 address changed at hh:mm (old: …)".
5. Send `လိပ်စာ ပြောင်းချင်ပါတယ်` again, then `ဒဂုံ ၃လမ်း အမှတ် ၉`. Expect only "လိပ်စာ ပြင်ပြီးပါပြီ – ဒဂုံ 3လမ်း
   အမှတ် 9" (payment info is not sent twice).
6. Send `လိပ်စာ` alone. Expect no reply (it is not an address).
7. Cancel the cart. Order again, then answer the returning question with `ဖုန်းပြောင်းချင်တယ်`. Expect
   "ဖုန်းနံပါတ်အသစ် ပို့ပေးပါနော်။". Send a new number. Expect "ဖုန်းနံပါတ် ပြင်ပြီးပါပြီ – …" + payment info;
   Chats shows the new number first.

## 2026-10-17 — v4.9: smart greeting (docs/SPEC-v4.9-greeting.md)
**Live case:** order waiting for payment (payment info 01:47); "hi" at 02:31 got no reply. The old rule
answered a greeting only if we hadn't messaged the customer for 6 h.

**What was built**
- A message that is only a greeting is always answered, unless a greeting reply already went to this
  customer in the last 30 minutes (new setting on the Learning page, "Greeting reply again only after
  this many minutes", default 30; 0 = always). A repeated "hi" inside the window gets no auto reply and
  shows in Needs you as unanswered after 2 min (greeting added to the safety net's question intents).
- The reply follows the customer's state (new editable templates):
  - no order: greeting_reply
  - open cart: greeting_cart = list + total + the same closing question as the cart list
    (phone / address / "same as last time?")
  - waiting for a new address / phone (4.8): the ask_new_* question again (never payment info)
  - waiting_payment: greeting_waiting_payment (items, total, "send the screenshot")
  - photo_received: greeting_photo_received
  - paid / packed: greeting_preparing with Order #
  - sent_out: greeting_sent with Order # and date
- "hi swy 5ml ဘယ်လောက်လဲ" stays a price question.
- Auto-reply OFF: the same text on the one-tap "👋 Reply greeting" button.
- `cart.closing_line()` is now shared by the cart list and the greeting.

**Decision to check (literal reading of rule 1).** The 6 h rule now only decides the leading "မင်္ဂလာပါ။".
So when we messaged the customer in the last 6 h, as in the live case (44 min), the reply starts without
it: "Stronger With You Intensely 5ml အတွက် စုစုပေါင်း 18,000 ကျပ် လွှဲပြီးရင် … ဘာများ ထပ်ကူညီပေးရမလဲ။". After 6 h
it starts with "မင်္ဂလာပါ။ ". The greeting is never doubled. If the owner prefers "မင်္ဂလာပါ။" on every reply
to "hi", it is a one-line change in app/orders/greeting.py.

**Tests:** 397 passed, 1 skipped (was 387 + 1). 10 new tests in tests/test_v49_greeting.py:
- I1: the exact live case, plus the after-6 h variant.
- I2: no order; 30-min window; Needs you after 2 min; answered again after 35 min; the window setting.
- I3: open cart without phone; auto OFF gives a one-tap button with the same text.
- I4: payment photo, paid, sent out with the date.
- I5: waiting for a new address.
- I6: greeting + price question.
- All earlier tests pass unchanged (B5 greetings included).

**Deployed:** backup product_requests_2026-10-16T2016Z.dump (no migration), parser + web restarted,
health ok. The earlier unanswered "hi" from the live case already has an auto decision, so it is not
answered late.

**Owner test (second Telegram account, Auto-reply ON)**
1. With no order, send `hi` → "မင်္ဂလာပါ။ ဘာကူညီပေးရမလဲ။" (or without "မင်္ဂလာပါ။" if we wrote to you in the last
   6 h).
2. Send `hi` again at once → no reply. After 2 min it is in "🟡 Needs you" as unanswered.
3. Send `stw intensely 5ml ယူမယ်` (the list comes), then `hi` → "ခြင်းထဲမှာ ဒါတွေ ရှိပါတယ် – … စုစုပေါင်း 18,000
   ကျပ်ပါ။" + the phone question. (If the window from step 1 is still open, wait 30 min or set the minutes
   on the Learning page to 1.)
4. Send your phone and address → payment info. Then `hi` → "… အတွက် စုစုပေါင်း … ကျပ် လွှဲပြီးရင် transaction id
   ပါတဲ့ screenshot ပို့ပေးပါနော်။ ဘာများ ထပ်ကူညီပေးရမလဲ။".
5. Send a payment screenshot, then `hi` → "ငွေလွှဲ screenshot ရပါပြီ…". Approve it, then `hi` → "Order #N ကို
   ပြင်ဆင်နေပါတယ်…". Mark it sent out, then `hi` → "Order #N ကို dd/mm/yyyy မှာ ပို့ပြီးပါပြီ…".
6. Send `hi swy 5ml ဘယ်လောက်လဲ` → the price reply.
