# Epic 5.4 — UI / UX clean-up of the whole dashboard. Goal-driven loop. Build AFTER 5.3 (speed).
Owner 2026-11-06 approved the mockups below ("I like that") and asked for a review of the whole UI and user
experience, then a plan. PC browser first (Chrome / Edge, ≥ 1024 px); phone must not break (ui_check stays green).
Same loop as 4.20 / 4.21: measure -> fix the biggest problem -> run everything again, until the goal is met.

## Approved mockups (match them: read the .dc.html for exact colours, sizes, wording)
- docs/mockups/products-clean.dc.html — Products & prices (content next to the menu, big title, segmented
  Products · Prices · Stock, search + button, rows with brand above name, price chips, "Added here" tag,
  footer with "Show 10 20 50 100", "1–10 of N", page buttons).
- docs/mockups/ai-paged.dc.html — AI helper (settings grouped, labels above fields, evaluation tiles, AI calls
  table with Mode badges, paging footer that works).
- Style base stays 4.21 (iOS look, app.css variables). Same fonts. No new libraries.

## Review findings (planning chat read base.html, settings.html and the owner's screenshots)
F1 Content column is centred in the whole window, leaving a big empty gap beside the menu (Products, AI).
F2 Long lists have no paging: AI "Last 50 calls", Products, and probably Customers, Orders history, Messages,
   Stock moves, Activity, Learning. Slow to scroll, slow to load.
F3 Settings is ONE long page of ~8+ separate cards, each with its own Save button, emoji in every heading
   (🔔 🤖 📦 🧪), technical words for the owner/staff (".env", "ALERT_BOT_TOKEN", "SHADOW", "TEST_PAY_CODE").
F4 The menu hides 15 pages behind "Settings"/"More"; some appear twice (Products, Sales, Stock), "Inbox" (/) and
   "Chats" are two doors to almost the same thing, Practice / Help / Health / Learning / Reports are buried.
F5 Links are blue + underlined everywhere (look like a 2005 website), tables are dense text, little hierarchy
   (no page title + subtitle pattern, buttons of different sizes, several primary buttons per page).
F6 Forms: labels beside/under inconsistently, no inline "saved" feedback per section, no "unsaved changes" hint.
F7 Empty states and errors are bare text; no loading state; error page does not say what to do next.
F8 Plain-language gaps for non-technical Burmese staff: mixed English/Burmese labels, jargon (SHADOW, AUTO,
   intent, alias, normalize), numbers without units (Ks / ml / s).
F9 Wide screens: nothing uses the space well (chat is fine after 4.21; the other pages are narrow columns).

## GOAL (loop until all true)
- **X1 Same look everywhere:** every page uses the shared page pattern: title (34 px) + one-line subtitle,
  optional segmented control, content cards 16 px radius, ONE primary button per section, links styled as in
  the mockups (no default blue underline except in running text), same table/list style, same empty and error
  states. Check with screenshots next to the mockups and fix visible differences.
- **X2 Paging on every long list** with the same footer: "Show 10 · 20 · 50 · 100" (default 20; Products 20,
  AI calls 10), "a–b of N", ‹ 1 2 3 › with ellipsis for many pages. The server pages with LIMIT/OFFSET and a
  COUNT (never loads all rows); `?page=&per=` in the URL (back button, links work); the choice of `per` is
  remembered per user in a small non-sensitive cookie. HTMX swaps the list only (no full reload).
- **X3 Settings re-organised** like iOS Settings: left list of sections (Shop · Orders & payments · Auto-reply ·
  AI helper · Alerts & backup · Inventory · Test mode · Users · My account · Health · Help), right = that
  section as grouped boxes; each section has ONE Save, shows "Saved ✓" inline, and warns "unsaved changes" when
  leaving. No emoji in headings (use the icon set). Technical text (.env names, modes) moves into a collapsed
  "Technical details" line under the field, owner only.
- **X4 Simple menu:** sidebar = Chats · Orders · Payments · Customers · Products & prices · Sales · Settings.
  Everything else is inside Settings (X3) or the "?" help menu. "Inbox" (/) redirects to Chats. Staff sees only
  what staff may use. Old URLs still work. The phone tab bar keeps Chats · Orders · Payments · More.
- **X5 Words:** one glossary (docs/GLOSSARY.md, EN + MY): every label a staff member sees uses plain words and
  units; jargon is replaced or explained by a "?" popover. Burmese strings added to i18n_my.py for every new
  label; ui_check still covers en + my.
- **X6 No dead ends:** every empty list says what to do next with a button; the error page offers "Back to
  Chats" + "Try again" and, for the owner, the request id; slow actions show a spinner / disabled button;
  destructive actions use the confirm dialog (4.15) and say what will happen.
- **X7 Wide screens:** pages other than Chats use a left-aligned container (max 1120–1280 px) next to the menu;
  tables switch to a two-column layout where it helps (Orders: list + detail panel like Chats).
- **X8 Nothing lost / nothing slower:** every action in tests/fixtures/ui_inventory.json is still reachable for
  the same role (update the inventory with a note per moved control); full pytest, scripts/ui_check.py
  C1-C7 (every page × role × language × width) and the 5.3 perf_check numbers stay green.

## Work plan (in this order; each step ends with tests + deploy + a REPORT.md scoreboard line)
U0 Audit: screenshot every page (en + my, 1440 and 390 px) into ui-shots/before/; write the list of
   differences from the mockups and the findings F1-F9 per page in REPORT.md (this becomes the scoreboard).
U1 Shared building blocks in templates + app.css: page header, segmented control, list card, price chip, badge,
   pager macro (X2), form row (label above), empty state, inline "Saved ✓", help popover.
U2 Pager backend helper `paginate(query, page, per)` used by every list route; tests for edges (page 0, per
   not in 10/20/50/100, last page, empty, N = exact multiple, huge page number).
U3 Products & prices + AI helper (the two mockups), then Customers, Orders (list + detail), Payments, Stock,
   Sales, Learning, Reports, Activity, Users.
U4 Settings re-organisation (X3) + menu (X4) + redirects.
U5 Words + glossary + Burmese pass (X5), empty/error states (X6).
U6 LOOP: run full pytest + ui_check + perf_check + screenshot comparison with the mockups -> list every failure /
   visible difference / bug -> fix the biggest -> run again. Do not stop at a loop count, do not lower the goal,
   skip, delete or xfail tests. After every loop add one line to REPORT.md "5.4 scoreboard" (loop, tests,
   ui_check fails, pages not matching the pattern, lists without paging, bugs left). Commit + push + deploy after
   each loop that improves the score. Stop early ONLY for something the owner must decide (write it in
   REPORT.md and PLAN.md RESUME HERE). Restart the web service in the same step as any template/code deploy so
   the site is never half-updated (a half-deployed 5.3 caused a login 500 on 2026-11-05).

## Tests
paginate() edges; every list route returns ≤ per rows and a correct total; `per` cookie remembered, invalid
values ignored; pager links keep other filters (search, tab); settings sections save independently and keep
permissions (staff cannot open owner sections); old URLs redirect; every page uses the page header / no
default-blue-underline links (CSS test or ui_check rule); no emoji in h1/h2; empty states present; i18n keys for
my; ui_inventory still complete; full suite + ui gate green.

## OWNER TEST 5.4 (PC browser)
1. Products & prices and AI helper look like the mockups. AI calls show 10 rows; click 20 / 50 / 100 and page
   buttons; press Back — you return to the same page.
2. Customers, Orders, Stock moves, Activity: same footer, same look.
3. Settings: pick each section on the left, change one value, Save — "Saved ✓" appears; leave with unsaved
   change — it warns you.
4. Menu has 7 items; everything else is under Settings. Old bookmarks still open.
5. Switch to မြန်မာ: no English jargon left on the main pages; "?" explains the hard words.
6. Open an empty list (e.g. search for "zzzz") — it tells you what to do next.
