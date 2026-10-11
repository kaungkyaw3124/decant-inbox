# Plan & Status

Read CLAUDE.md first. This file tracks where we are.

## RESUME HERE (2026-10-11, 02:20, owner went to sleep)
- Phases 1-4 done and verified by owner. Phase 5: services, tunnel (decant-tunnel ->
  TUNNEL_URL), client-IP lockout and scripts/status.sh done (2026-10-11 16:45 UTC).
  Owner sudo done (pg client 18, Linger=yes); first backup ok and restore-tested.
  Still open: owner reboot test. See "Phase 5 spec" below.
- New session start: read CLAUDE.md, this file, and the last entries of REPORT.md.
- If the listener was down overnight, run import_history (stop the listener first)
  to fill the gap; Telegram keeps the messages, so nothing is lost.

## Status
| Phase | What | Status |
|---|---|---|
| 0 | VPS hardening, Docker, GitHub | ✅ Closed (rest of security deferred) |
| 1 | Database models, migration, seed products/aliases | ✅ Done |
| 2 | Telethon listener + history import | ✅ Done (30-day import run, listener live) |
| 3 | Rule-based parser + tests | ✅ Done (worker live; needs real catalog + labelled samples) |
| 3b | AI fallback (optional) | ⬜ Not started |
| 4 | Dashboard + Tailscale (private access) | ✅ Dashboard verified by owner via SSH tunnel (2026-10-11). Tailscale (phone access) still optional |
| 5 | Run 24/7, backups, health page | 🟡 services + Cloudflare quick tunnel live; first backup done + restore-tested, linger on; waiting: owner reboot test |

## Phase 0 checklist
- [x] Step 0: rollback safety net scripts in ~/hardening/
- [x] Owner's SSH key login tested on port 10066
- [x] Step 1: ufw (allow 22/tcp + tailscale0; remove old 443 rule)
- [ ] Step 2: SSH hardening drop-in (no passwords, no root login)
- [ ] Steps 3+4 in ONE script: fail2ban (sshd jail) + unattended security upgrades
- [x] Project pushed to GitHub (no secrets committed)
- Moved to Phase 4: Tailscale + compose web service on 127.0.0.1:8080
  (not needed until there is a dashboard to open)

## NEXT (owner decision 2026-10-10: no more security work now — build the project)
- Phase 0 is CLOSED. Do not start any more hardening, firewall, SSH or update work.
  Deferred to later (owner will ask): auto-updates (apt-daily.timer is masked),
  re-checking the SSH drop-in, Tailscale (Phase 4).
- Do not ask the owner to run sudo unless a project step truly needs it
  (e.g. installing python3-venv or Docker packages); bundle it into one command.
1. Finish Phase 1: venv, migration, seed twice (idempotent), tests, push.
2. Go straight on to Phase 2 code (listener + history import). The owner will add
   TG_API_ID / TG_API_HASH to .env and type the login code when you are ready.
3. Then Phase 3 (parser), Phase 4 (dashboard + Tailscale), Phase 5.

## Phase 5 spec (agreed 2026-10-11)
Owner wants to open the dashboard from any device with internet, no app, and avoid
Tailscale (VPN-like traffic is often blocked in Myanmar). Decision: Cloudflare QUICK
TUNNEL (free, random *.trycloudflare.com URL, no domain, no inbound ports).
1. Run 24/7: listener, parser worker, web and the tunnel as services that start on
   boot and restart on crash (systemd system units or user units with linger; give
   the owner ONE sudo command if needed). Stop the current nohup processes first.
2. Tunnel: cloudflared binary (official release; ~/.local/bin is fine, no sudo needed)
   running `cloudflared tunnel --url http://127.0.0.1:8080`. Parse the
   https://*.trycloudflare.com URL from its log and write it to TUNNEL_URL in the
   project folder (git-ignored) every time it starts. Owner reads it via SSH.
3. Web behind the tunnel: trust CF-Connecting-IP / X-Forwarded-For from 127.0.0.1 only,
   so the login lockout counts the real client IP; keep the Secure cookie (HTTPS via
   Cloudflare). Login lockout stays.
4. Daily pg_dump backup (keep 14 days) in backups/ (git-ignored), plus a restore note.
5. Health: /healthz already exists; a tiny status script prints services + TUNNEL_URL.
6. Prove it: owner reboots the VPS; everything returns on its own; new URL in TUNNEL_URL.
Fallback access stays: SSH tunnel `ssh -p 10066 -L 8080:127.0.0.1:8080 ...`.
Later option: a real/DuckDNS domain with a named tunnel or direct HTTPS for a fixed URL.
Do NOT send the URL via the owner's Telegram account (account is read-only).

## Test data (added by planning chat, 2026-10-11)
- data/products.csv + data/aliases.csv: 20 popular decant perfumes with English and
  Burmese nicknames. TEST catalog only; the owner replaces it later.
- tests/fixtures/synthetic_messages.csv: 32 made-up messages (no customer data, safe
  to commit) with expected intent/product/size. Checked against rules-1: 32/32.
- To do (VPS): re-seed, reparse_all, and add a test that runs the parser over the
  fixture (same columns as data/sample_messages.csv) so it runs on every pytest.

## Owner inputs needed
- [ ] data/products.csv (`brand,name`): top 10–20 perfumes to start
- [ ] data/aliases.csv (`product_name,alias`)
- [x] api_id + api_hash from my.telegram.org, typed into .env on the server only
- [ ] data/sample_messages.csv, kept OUT of git: run `.venv/bin/python -m scripts.export_samples`,
      correct the intent/product/size_ml columns, then `.venv/bin/pytest tests/test_parser_samples.py`

## Later (not v1)
AI fallback → inventory in ml per bottle + supplies → orders & statuses →
payments → Viber → reports. Each is a new module with its own tables.
