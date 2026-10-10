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
