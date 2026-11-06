# Plan & Status

Read CLAUDE.md first. This file tracks where we are.

## NEXT TASK (written by the planning chat; Claude Code runs it with /next)
Task: v5.3 PERFORMANCE (PC browser only): static caching + versioned URLs, compression, no full reloads, prefetch,
SSE, faster queries, nice-d tests, trusted-device login, keyboard — docs/SPEC-v5.3-performance-pc.md (goal P1-P5).
Status: DONE 2026-11-06 — see REPORT.md

## RESUME HERE (updated 2026-11-06 by Claude Code)
- v1-v4.12 DONE. AI AUTO, brake ON, ai_address ON, ai_screenshot OFF.
- v4.13 hotfix (docs/SPEC-v4.13-hotfix.md) DONE + deployed 2026-10-17: Q0-Q5, R1-R6, evals PASS. Owner test 4.13
  pending (REPORT.md "OWNER TEST SCRIPT 4.13").
- v4.14 test payment code DONE + deployed 2026-10-30 (feature OFF until owner sets TEST_PAY_CODE in .env).
  Owner test 4.14 pending (REPORT.md "OWNER TEST SCRIPT 4.14").
- v4.15 new UI (Bootstrap, mobile-first) DONE + deployed 2026-10-31: UI gate 300 views 0 fails, 719 tests.
  Owner test 4.15 pending (REPORT.md "OWNER TEST SCRIPT 4.15").
- v4.16 hotfix (new order after a paid one) DONE + deployed 2026-10-31: 743 tests, address eval PASS, UI gate quick PASS.
  Owner test 4.16 pending (REPORT.md "OWNER TEST SCRIPT 4.16"; needs TEST_PAY_CODE + Test account ON).
- v4.17 hotfix 2 (size not sold → size question, address never an item, grid = Mandalay, old-cart line) DONE +
  deployed 2026-10-31: 770 tests, both AI evals PASS, UI gate quick PASS. Owner test 4.17 pending (REPORT.md).
- v4.20 automation goal DONE + deployed 2026-11-02: sim 100% auto / 0 wrong / 0 silent, live replay 87.7%,
  809 tests (13.5 min; 8 min not reachable on 2 CPUs). Owner test 4.20 pending (REPORT.md). Fill the Delivery fee FAQ.
- v4.21 Messenger/iOS dashboard DONE + deployed 2026-11-02: full UI gate 300 views 0 fails, U4 3-tap flows pass.
  Owner test 4.21 pending (REPORT.md).
- v4.18 speed DONE + deployed 2026-11-02 (NOTIFY wake-ups, AI pool, 0.7 s / 0.3-0.8 s, instant holding reply).
  Owner test 4.18 pending (REPORT.md): it gives the live "after" numbers on /health → Speed.
- v5.0 go-live pack DONE + deployed 2026-11-02: alerts / off-server backup OFF until the owner sets ALERT_BOT_TOKEN,
  ALERT_CHAT_ID, BACKUP_PASSPHRASE (REPORT.md "How to switch on"); 2-step login: owner turns it on in My account.
- v5.1 inventory DONE + deployed 2026-11-02 (empty until the owner adds bottles: manual in-stock flags until then).
- v5.2 customer care DONE + deployed 2026-11-02 (feedback OFF until switched on).
- v5.3 PC speed DONE + deployed 2026-11-06: static cache + versioned URLs, gzip, boosted menu, prefetch, SSE,
  trusted computer, keyboard; warm pages 0.2-0.5 s / 0 KB (was ~2.2 s / 680 KB), send 0.25 s. NOT met yet: customer
  switch p90 1.27 s (goal 0.5) and server p90 ≤ 200 ms (chat page ~49 queries) -> follow-up for the planning chat.
- Owner tests pending: 4.13-4.21, 5.0-5.3 (REPORT.md).
- NEXT: v5.4 UI/UX clean-up (QUEUE item 11).
- Owner checks: `bash scripts/status.sh`; AI numbers at /ai.

## Status
| Phase | What | Status |
|---|---|---|
| 0 | VPS hardening, Docker, GitHub | ✅ Closed (rest of security deferred) |
| 1 | Database models, migration, seed products/aliases | ✅ Done |
| 2 | Telethon listener + history import | ✅ Done (30-day import run, listener live) |
| 3 | Rule-based parser + tests | ✅ Done (worker live; needs real catalog + labelled samples) |
| 3b | AI fallback (optional) | ✅ Replaced by v4.6 AI helper |
| 4 | Dashboard + Tailscale (private access) | ✅ Dashboard verified by owner via SSH tunnel (2026-10-11). Tailscale (phone access) still optional |
| 5 | Run 24/7, backups, health page | ✅ Done: reboot test passed 2026-10-11 (all services back, health ok, new tunnel URL) |
| 6 | v2: replies, cart, payment check, orders (docs/SPEC-orders.md) | ✅ Steps 1-5 done |
| 7 | v3 (docs/SPEC-v3.md): after payment, FAQ, sales | ✅ Steps 6-8 done (owner test pending) |
| 8 | v4 (docs/SPEC-v4.md): Learning Inbox | ✅ 4.1-4.5 done (owner test + staff test pending) |
| 9 | v4.6 (docs/SPEC-v4.6-ai.md): AI helper, OpenAI | ✅ S0-S5 done, eval gate passed, live in SHADOW (owner test pending) |
| 10 | v4.7 (docs/SPEC-v4.7-graduation.md): SHADOW -> AUTO graduation, brake, weekly summary | ✅ Done, live (auto-graduate ON) |
| 11 | v4.8 (docs/SPEC-v4.8-change-info.md): change address / phone, live bug fix | ✅ Done, live (owner test pending) |
| 12 | v4.9 (docs/SPEC-v4.9-greeting.md): smart greeting | ✅ Done, live (owner test pending) |
| 13 | v4.10 (docs/SPEC-v4.10-interruptions.md): interruptions, resume line, locked paid orders | ✅ Done, live (owner test pending) |
| 14 | v4.11 (docs/SPEC-v4.11-ai-first.md): AI-first (AUTO, multi-action, customer chooses, auto-learning, simple card) | ✅ Done, live in AUTO (owner test pending) |
| 15 | v4.12 (docs/SPEC-v4.12-address-payment-ai.md): AI address assistant, address gates, AI screenshot reader | ✅ Done, live (ai_address ON, ai_screenshot OFF; owner test pending) |
| 16 | v4.13 (docs/SPEC-v4.13-hotfix.md): hotfix from live test: never silent (holding reply + watchdog), order_start, address cleaning, no-place = invalid, Mandalay grid | ✅ Done, live (owner test pending) |
| 17 | v4.14 (docs/SPEC-v4.14-test-payment-code.md): secret test payment code from test accounts, T-numbered test orders, kept out of sales | ✅ Done, live (owner test pending; set TEST_PAY_CODE) |
| 18 | v4.15 (docs/SPEC-v4.15-ui-bootstrap.md): Bootstrap 5 mobile-first UI, phone tab bar, UI gate (scripts/ui_check.py) | ✅ Done, live (owner test pending) |
| 19 | v4.16 (docs/SPEC-v4.16-hotfix-new-order-after-paid.md): same-message contact wins, open cart gets changes after a paid order, str grid, test code too early | ✅ Done, live (owner test pending; set TEST_PAY_CODE) |
| 20 | v4.17 (docs/SPEC-v4.17-hotfix-more-automatic.md): size not sold → automatic size question, address/phone never items, grid without city = Mandalay, old-cart line | ✅ Done, live (owner test pending) |
| 21 | v4.20 (docs/SPEC-v4.20-automation-goal.md): automation goal — simulator (214 scenarios) + strict judge + live replay; G1-G4 met | ✅ Done, live (owner test pending; fill Delivery fee FAQ) |
| 22 | v4.21 (docs/SPEC-v4.21-ios-messenger-ui.md): Messenger workspace, iOS look, phone tab bar | ✅ Done, live (owner test pending) |
| 23 | v4.18 (docs/SPEC-v4.18-speed.md): first reply in ~2 s, AI pool, instant holding reply, Speed on /health | ✅ Done, live (owner test pending) |
| 24 | v5.0 (docs/SPEC-v5.0-go-live-pack.md): alert bot, encrypted off-server backup, 2-step login, packing slips | ✅ Done, live (secrets OFF until set; owner test pending) |
| 25 | v5.1 (docs/SPEC-v5.1-inventory.md): stock in ml, auto out-of-stock, deduct on packed, Stock page | ✅ Done, live (owner test pending) |
| 26 | v5.2 (docs/SPEC-v5.2-customer-care.md): customer profiles, reorder list, feedback after delivery | ✅ Done, live (feedback OFF; owner test pending) |
| 27 | v5.3 (docs/SPEC-v5.3-performance-pc.md): PC speed: browser cache, gzip, no full reloads, prefetch, live updates, trusted computer, keyboard | ✅ Done, live (P1/P4/send met; switch + server time follow-up; owner test pending) |

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

## Backlog (owner asked to be reminded)
- ~~DAILY SALES dashboard~~ done in v3 Step 8 (/sales).
- Fixed domain for the dashboard (instead of the changing trycloudflare.com URL).

## Later (not v1)
AI fallback → inventory in ml per bottle + supplies → orders & statuses →
payments → Viber → reports. Each is a new module with its own tables.

## QUEUE (planning chat adds tasks here; /next takes the first TODO when NEXT TASK is DONE)
1. v4.15 New UI/UX with Bootstrap 5, mobile-first — docs/SPEC-v4.15-ui-bootstrap.md (U0-U5, goal-driven loop,
   OWNER TEST 4.15). Status: moved to NEXT TASK 2026-10-31
2. v4.16 HOTFIX from live test 2026-10-31 09:46 — docs/SPEC-v4.16-hotfix-new-order-after-paid.md (Q0-Q4, R1-R7,
   OWNER TEST 4.16). Status: moved to NEXT TASK 2026-10-31
3. v4.17 HOTFIX 2 from live test 2026-10-31 10:27 — docs/SPEC-v4.17-hotfix-more-automatic.md (P0-P5, S1-S7,
   OWNER TEST 4.17). Status: moved to NEXT TASK 2026-10-31
4. v4.20 AUTOMATION GOAL (goal-driven loop until G1-G4 met: ≥90% automatic, 0 wrong, never silent, live replay
   ≥85%) — docs/SPEC-v4.20-automation-goal.md (A0-A6, OWNER TEST 4.20). Status: moved to NEXT TASK 2026-10-31
5. v4.21 DASHBOARD REDESIGN: Messenger layout + iOS look — goal-driven loop until U1-U4 met —
   docs/SPEC-v4.21-ios-messenger-ui.md (mockups docs/mockups/ios-*.dc.html; replaces v4.19, OWNER TEST 4.21). Status: moved to NEXT TASK 2026-11-02
   (v4.19 NEEDS YOU CARDS: replaced by v4.21, do not build separately)
6. v4.18 SPEED: first reply within 3 s — docs/SPEC-v4.18-speed.md (S0-S5, T1-T8, OWNER TEST 4.18). Status: DONE 2026-11-02 (run with the queue; see REPORT.md)
7. v5.0 GO-LIVE PACK: alert bot, encrypted off-server backup, 2-step login, packing slips — docs/SPEC-v5.0-go-live-pack.md
   (goal L1-L4; secrets stay OFF until the owner sets them). Status: DONE 2026-11-02
8. v5.1 INVENTORY in ml: bottles, vials, auto out-of-stock, deduct on packed — docs/SPEC-v5.1-inventory.md (goal I1-I4). Status: DONE 2026-11-02
9. v5.2 CUSTOMER CARE: profiles, one-tap reorder list, feedback after delivery — docs/SPEC-v5.2-customer-care.md
   (goal C1-C3). Status: DONE 2026-11-02
10. v5.3 PERFORMANCE (PC browser only): static caching + versioned URLs, compression, no full reloads, prefetch, SSE,
   faster queries, nice-d tests, trusted-device login, keyboard — docs/SPEC-v5.3-performance-pc.md (goal P1-P5). Status: moved to NEXT TASK 2026-11-03
11. v5.4 UI/UX CLEAN-UP of the whole dashboard (shared page pattern, paging 10/20/50/100 on every long list, Settings by section,
   simple 7-item menu, plain words EN+MY, empty/error states) — docs/SPEC-v5.4-ui-ux-cleanup.md (goal X1-X8); needs 5.3 first. Status: TODO
