# v5.5 HOTFIX — page layout is not centred / not full width (PC). Goal-driven loop.
Owner 2026-11-08 (screenshots of Products and Login at 1668 and 1916 px wide): "those are not align center or not
full page. check and fix". Same loop: fix -> screenshot at several widths -> fix the biggest difference -> repeat.

## What the planning chat found
- app.css ~line 637, desktop rule: `main:not(.ws-main) { margin: 0; max-width: 1200px; padding: 32px 40px 48px; }`
  = a 1200 px box glued to the LEFT of the content area. On a wide monitor the whole right side is empty
  (Products: content ends at ~1380 px of 1668; Login: the card sits at x≈410-790 of 1916, far left of centre).
- The 4.21/5.4 spec said "left-aligned container". The owner now says it looks wrong: wanted = centred on the
  page, using the full width in a sensible way.
- Login is not inside the sidebar layout (signed out) but inherits the same left-glued `main`.

## GOAL (all true at widths 1280, 1440, 1668, 1920, 2560 px — and phone/tablet unchanged)
- **L1 Login (and 2-step code, error) card is centred horizontally and sits in the upper third vertically**
  (no sidebar when signed out; nothing glued left).
- **L2 Signed-in pages (except the Chats workspace):** the content area = window minus the 220 px sidebar. Content
  is **centred in that area** (margin-inline: auto) with `max-width: min(1440px, 100% - 80px)`; at ≥ 1900 px
  width the max-width grows to 1680. List pages (Products, Customers, Orders, Stock, Activity, AI calls) use the
  full container width: header, search, table card and pager share the SAME left and right edges.
- **L3 Tables use the width:** columns share the extra space (Products: Product 1fr, Prices chips fill, numbers
  right-aligned), no big empty area inside the card; chips wrap only when needed.
- **L4 Same everywhere:** Products, Prices, Stock, Customers, Orders (list + detail), Payments, Sales, Settings
  (sections + form), AI helper, Health, Help, Learning, Reports, Users, My account, slips excluded (print).
  One CSS rule/class for the page container (`.page`), no per-page max-widths left (grep for `max-width` on
  main/page wrappers; remove the old `main { max-width: 880px }` and `main.wide` leftovers).
- **L5 Chats workspace unchanged** (already full width); phone/tablet unchanged (ui_check stays green).
- **L6 Proof:** scripts/ui_check.py gets a rule C8: at 1440, 1920 and 2560 px, for every page × role, the content
  box is horizontally centred in the content area (|left gap − right gap| ≤ 2 px) and its width ≥ 70% of the
  content area (or equals max-width); login card centre within 2 px of the window centre. Screenshots saved to
  ui-shots/5.5/ (1440, 1920, 2560 × Products, Customers, Orders, Settings, AI, Login) and listed in REPORT.md.

## Loop
Fix container + login -> run ui_check (C1-C8 all pages) + screenshots -> list every page that fails C8 or looks
off -> fix the biggest -> run again. Do not lower the goal or skip pages. Add one line per loop to REPORT.md
"5.5 scoreboard" (loop, pages failing C8, ui_check fails). Restart the web service in the same step as the deploy.
Commit + push + deploy after each loop that improves the score. Stop only for something the owner must decide.

## OWNER TEST 5.5 (PC browser, maximise the window)
1. Log out: the Login card is in the middle of the page.
2. Products & prices, Customers, Orders, Settings, AI helper: the content is centred between the menu and the
   right edge; the title, search box, table and page buttons line up on both sides.
3. Make the window narrower (drag) and wider (full screen): nothing sticks to one side, nothing scrolls sideways.
4. Chats still use the whole screen. Phone view still works.
