# Plan & Status

Read CLAUDE.md first. This file tracks where we are.

## Status
| Phase | What | Status |
|---|---|---|
| 0 | VPS hardening, Tailscale, Docker, GitHub | 🟡 In progress (step 0 prepared; waiting for SSH key test) |
| 1 | Database models, migration, seed products/aliases | ⬜ Not started |
| 2 | Telethon listener + history import | ⬜ Not started |
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

## NEXT (speed plan, agreed 2026-10-10)
1. Step 2, then steps 3+4 as one script. Owner runs each with sudo.
2. Start Phase 1 right away. If data/products.csv and data/aliases.csv are not
   there yet, create them with 3 example rows (YSL Stronger With You Intensely,
   with aliases from CLAUDE.md) so models, migration and seed can be built and
   tested now. The owner replaces them with the real list later; the seed must be
   safe to re-run (upsert, no duplicates).
3. Then Phase 2 (owner provides api_id/api_hash in .env and types the login code).

## Owner inputs needed
- [ ] data/products.csv (`brand,name`): top 10–20 perfumes to start
- [ ] data/aliases.csv (`product_name,alias`)
- [ ] api_id + api_hash from my.telegram.org, typed into .env on the server only
- [ ] data/sample_messages.csv (after Phase 2 history import), kept OUT of git

## Later (not v1)
AI fallback → inventory in ml per bottle + supplies → orders & statuses →
payments → Viber → reports. Each is a new module with its own tables.
