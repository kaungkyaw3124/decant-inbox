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
