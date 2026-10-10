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
