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
| 4 | Dashboard (private via Tailscale) | ⬜ Not started |
| 5 | Run 24/7, backups, health page | ⬜ Not started |

## Phase 0 checklist
- [x] Step 0: rollback safety net scripts in ~/hardening/
- [x] Owner's SSH key login tested on port 10066
- [ ] Step 1: ufw (allow 22/tcp + tailscale0; remove old 443 rule)
- [ ] Step 2: SSH hardening drop-in (no passwords, no root login)
- [ ] Step 3: fail2ban (sshd jail)
- [ ] Step 4: unattended security upgrades
- [ ] Step 5: Tailscale installed; owner's phone + laptop joined
- [ ] Project pushed to GitHub (no secrets committed)
- [ ] compose.yaml prepared for the web service on 127.0.0.1:8080 (built in Phase 4)

## Owner inputs needed
- [ ] data/products.csv (`brand,name`): top 10–20 perfumes to start
- [ ] data/aliases.csv (`product_name,alias`)
- [ ] api_id + api_hash from my.telegram.org, typed into .env on the server only
- [ ] data/sample_messages.csv (after Phase 2 history import), kept OUT of git

## Later (not v1)
AI fallback → inventory in ml per bottle + supplies → orders & statuses →
payments → Viber → reports. Each is a new module with its own tables.
