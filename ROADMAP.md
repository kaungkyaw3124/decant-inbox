# Decant Inbox — Roadmap

Project: **Decant Inbox** — Telegram order assistant + dashboard for a perfume decant shop.
Structure: Project → Release (v1, v2…) → Epic → Story (with acceptance tests) → Tasks.
Detailed specs live in docs/; status and "resume here" in PLAN.md; build log in REPORT.md.

| Release | Name | Goal | Status | Spec |
|---|---|---|---|---|
| v1 | MVP Inbox | Read Telegram messages, understand them, show them in a dashboard, run 24/7 | ✅ Done | CLAUDE.md (Phases 0-5) |
| v2 | Replies & Orders | Reply, cart, phone/address, payment info, auto mode, payment check, Order ID | ✅ Done | docs/SPEC-orders.md (Steps 1-5) |
| v3 | After-sale & Insights | Delivery statuses, reminders, cancel, Needs-you safety nets, FAQ, sales & profit | ✅ Done, owner testing | docs/SPEC-v3.md (Steps 6-8) |
| v4 | Learning Inbox | App learns from admins (teaching cards), reorder "the previous one", staff roles, Burmese UI, practice mode | 🔨 Building | docs/SPEC-v4.md |
| v5 | Inventory | Stock in ml per bottle, vials, low-stock alerts | 💡 Backlog | — |
| — | Backlog | Fixed domain, staff accounts/roles, Viber, real product list & payment numbers | 💡 | — |

## Mapping of old labels
- v1 "Phase 0-5" = v1 epics.  v2 "Step 1, 2, 3, 4, 4b, 4c, 4d, 5" = v2 epics.
- v3 "Step 6, 7, 8" = v3 epics. Old "Step 9 inventory" = v5. "Phase 3b AI fallback" = v4.

## v4 epics
- 4.1 Fix partial name matches (hawas bug)
- 4.2 Teaching cards: nicknames, intent phrases, not-stocked; greetings
- 4.3 Reorder "the previous one" from history + numbered choice
- 4.4 Roles (owner/staff), permissions, owner approval of learning
- 4.5 Burmese dashboard, help, practice mode, staff guide
- 4.8 Change address / phone (live bug fix) — docs/SPEC-v4.8-change-info.md
- 4.7 Shadow -> Auto graduation + safety brake + weekly AI summary — docs/SPEC-v4.7-graduation.md
- 4.6 AI helper (OpenAI gpt-6-luna) with evaluation gate, shadow -> auto — docs/SPEC-v4.6-ai.md
