# Decant Inbox — Roadmap

Project: **Decant Inbox** — Telegram order assistant + dashboard for a perfume decant shop.
Structure: Project → Release (v1, v2…) → Epic → Story (with acceptance tests) → Tasks.
Detailed specs live in docs/; status and "resume here" in PLAN.md; build log in REPORT.md.

| Release | Name | Goal | Status | Spec |
|---|---|---|---|---|
| v1 | MVP Inbox | Read Telegram messages, understand them, show them in a dashboard, run 24/7 | ✅ Done | CLAUDE.md (Phases 0-5) |
| v2 | Replies & Orders | Reply, cart, phone/address, payment info, auto mode, payment check, Order ID | ✅ Done | docs/SPEC-orders.md (Steps 1-5) |
| v3 | After-sale & Insights | Delivery statuses, reminders, cancel, Needs-you safety nets, FAQ, sales & profit | ✅ Done, owner testing | docs/SPEC-v3.md (Steps 6-8) |
| v4 | AI Assistant | Understand unclear messages with AI, self-learning patterns, reorder "the previous one" | 📝 Planning | docs/SPEC-v4-ai.md (to write) |
| v5 | Inventory | Stock in ml per bottle, vials, low-stock alerts | 💡 Backlog | — |
| — | Backlog | Fixed domain, staff accounts/roles, Viber, real product list & payment numbers | 💡 | — |

## Mapping of old labels
- v1 "Phase 0-5" = v1 epics.  v2 "Step 1, 2, 3, 4, 4b, 4c, 4d, 5" = v2 epics.
- v3 "Step 6, 7, 8" = v3 epics. Old "Step 9 inventory" = v5. "Phase 3b AI fallback" = v4.

## v4 epics (draft)
- 4.1 Bug fix: partial alias match (e.g. "hawas" matching inside "hawas for him").
- 4.2 AI understanding in shadow mode (AI suggests, admin accepts/fixes, accuracy shown).
- 4.3 Self-learning patterns (nicknames, intent phrases, typos) with approval.
- 4.4 Reorder / "the previous one" from customer history + numbered choice.
- 4.5 AI auto mode for high confidence; AI-drafted answers for questions (admin sends).
- 4.6 AI usage & cost page, daily cap, provider switch (AI_PROVIDER).
