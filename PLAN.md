# Plan & Status

Read CLAUDE.md first. This file tracks where we are.

## Status
| Phase | What | Status |
|---|---|---|
| 0 | VPS hardening, Docker, GitHub | ✅ Closed (rest of security deferred) |
| 1 | Database models, migration, seed products/aliases | ✅ Done |
| 2 | Telethon listener + history import | 🟡 In progress |
| 3 | Rule-based parser + tests | ⬜ Not started |
| 3b | AI fallback (optional) | ⬜ Not started |
| 4 | Dashboard + Tailscale (private access) | ⬜ Not started |
| 5 | Run 24/7, backups, health page | ⬜ Not started |

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

## Owner inputs needed
- [ ] data/products.csv (`brand,name`): top 10–20 perfumes to start
- [ ] data/aliases.csv (`product_name,alias`)
- [ ] api_id + api_hash from my.telegram.org, typed into .env on the server only
- [ ] data/sample_messages.csv (after Phase 2 history import), kept OUT of git

## Later (not v1)
AI fallback → inventory in ml per bottle + supplies → orders & statuses →
payments → Viber → reports. Each is a new module with its own tables.
