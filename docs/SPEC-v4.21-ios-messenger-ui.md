# Epic 4.21 — Dashboard redesign: Messenger layout, iOS look. Goal-driven loop. Build after 4.20.
Replaces 4.19 (its "one card per customer / Needs you" ideas are folded in here).

Owner 2026-11-02: "dashboard UI sucks". Chose: **Facebook Messenger layout** (menu left, customers left, click a
customer -> the conversation, auto replies visible) with **iOS fonts and theme**. Approved mockups (match them):
- docs/mockups/ios-laptop.dc.html (1280 px: icon/sidebar menu | chat list | conversation | customer panel)
- docs/mockups/ios-phone-list.dc.html (390 px chat list)  ·  docs/mockups/ios-phone-chat.dc.html (390 px chat)
The .dc.html files are plain HTML with inline styles: read them for exact colours, sizes, spacing, wording.

## GOAL (loop until all true)
- **U1 Looks like the mockups** at 390 / 768 / 1280 px (owner + staff, en + my): layout, colours, type, bubble
  styles, toggle, segmented control, tab bar. Check by screenshots next to the mockup screenshots (render the
  mockups with the same Playwright) and fix differences you can see.
- **U2 Nothing lost:** every action the 4.15 inventory (tests/fixtures/ui_inventory.json) lists is still
  reachable for the same role (moved is fine; update the inventory with a note per moved control).
- **U3 Gate green:** scripts/ui_check.py C1-C7 for every page × role × language × width; full pytest green.
- **U4 Owner flow in ≤ 3 taps** on the phone: open a customer that needs you → send the suggested reply;
  approve a payment; mark an order packed.

## Design rules (from the mockups)
- Font stack: `-apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, "Noto Sans Myanmar", system-ui,
  sans-serif`. Do NOT bundle SF Pro (Apple licence). Self-host Inter (woff2, OFL, licence file) as the
  non-Apple fallback; keep the vendored Noto Sans Myanmar; Burmese line-height ≥ 1.7.
- iOS system colours as CSS variables in app.css: blue #007AFF (primary), green #34C759, red #FF3B30, orange
  #FF9500, label #000, secondary #3C3C43/#8E8E93, grouped background #F2F2F7, fill #E5E5EA/#E9E9EB, separators
  #C6C6C8/#D1D1D6 at 0.5-1 px. Optional dark mode via prefers-color-scheme with iOS dark colours (owner may
  ask later; build the variables so it is easy).
- Bubbles: customer = grey #E9E9EB left; **auto reply = blue #007AFF right with caption "Auto-reply ·
  <status>"**; holding reply = light blue #CFE3FF with "Auto · please wait"; a reply typed/sent by a person
  = blue with caption "You" (or the staff name); scheduled/undo-able = caption "Sending in N s · Cancel".
  Photos (payment screenshots) as image bubbles with a "Check payment" button under them.
- Keep Bootstrap only where useful (grid/utilities/modals); the visual style comes from app.css.

## Screens
### Laptop (≥ 1024 px): one workspace, no page reloads between customers (HTMX swaps)
1. **Sidebar (220 px)**: Chats (count = customers needing you), Orders (to pack), Payments (to check),
   Products & prices, Sales, Settings at the bottom, and the **Auto-reply iOS toggle** (owner can switch;
   staff sees state only). Less-used pages (Learning, AI, Reports, Users, Health, Practice, Help, language,
   log out) under Settings or a "More" item.
2. **Chat list (340 px)**: large title "Chats", search (name / phone / order #), segmented control
   **All · Needs me N · Orders**. Rows: avatar initials, name, time, last message; last message from the bot
   shown as "Auto: …"; red time + blue/red dot when it needs you; small status pill (Paid / Cart / Sent).
   Sorted: needs-you first (longest waiting first), then most recent.
3. **Conversation**: header (avatar, name, city · N orders, "Pause auto-reply" text button), messages as
   bubbles (above), date separators, and at the bottom, when this customer needs a person, the **Needs you
   panel**: one line WHY in plain words + the suggested reply + **Send** / **Edit** (4.19 N2 rules: no %,
   no raw tokens, owner-only "Details" toggle). Quick-reply chips (Price, Cart list, Payment info, Ask
   address, …) + message box with the round blue send button. Undo window visible after Send.
4. **Customer panel (290 px, grouped iOS boxes)**: name, phone(s), Cart (lines, total, add/remove item),
   Deliver to (address + edit), order status + next-status buttons (packed / sent / delivered), payment
   check for this customer (open screenshot, transaction ID, Approve / Reject), Past orders, customer
   switches (never auto-reply, test account for owner, ignore).
### Phone (< 768 px): Messenger mobile
- Tab bar (frosted, iOS): **Chats · Orders · Payments · More** with red badges.
- Chats list as the mockup → tap → full-screen conversation ("‹ Chats" back); "Cart 33,000" pill opens the
  customer panel as a bottom sheet.
- Orders tab: status segmented control (Unpaid / Check / To pack / Sent) and order cards with one big
  next-status button + Slip (if the packing slip exists; otherwise leave it out).
- Payments tab: one card per check with the screenshot, expected vs received, Approve / Reject.
### Tablet (768-1023 px): chat list + conversation; customer panel as a sheet.

## Keep
All routes still work (old URLs redirect to the new workspace with the right customer/order open), CSRF,
HTMX targets, permissions, i18n keys (add new ones in i18n_my.py; staff test in Burmese), Telegram rules.
Existing tests: update only markup selectors; list every changed test in REPORT.md.

## Loop (owner: "let Claude Code test and fix bugs until it meets the goal")
U0 render the 3 mockups + current pages to ui-shots/ -> build sidebar/list/conversation/panel (laptop)
-> phone tabs -> other pages restyled with the same CSS. Then LOOP:
  run full pytest + scripts/ui_check.py + the simulator quick run (4.20) + compare screenshots with the mockups
  -> list every failure / visible difference / bug -> fix the biggest -> run everything again.
Keep looping until U1-U4 are ALL true. Do not stop at a loop count; do not lower the goal, skip, delete or
xfail tests. After every loop append one line to REPORT.md "4.21 scoreboard" (loop, tests, ui_check fails,
mockup differences left, bugs left). Commit + push + deploy after each loop that improves the score, so the
owner can look anytime. Stop early ONLY for something that needs the owner (a decision, sudo, a secret);
then write the question in REPORT.md and PLAN.md RESUME HERE and wait.

## OWNER TEST 4.21
Laptop: click customers in the list -> conversation changes without reload; auto replies are blue with
"Auto-reply"; a customer needing you is at the top with a red dot; Send the suggested reply; approve a
payment from the right panel; mark an order packed. Phone: Chats -> tap -> ‹ back; Cart pill; Orders and
Payments tabs; switch to မြန်မာ; nothing scrolls sideways.
