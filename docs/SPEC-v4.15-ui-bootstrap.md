# Epic 4.15 — New UI/UX with Bootstrap 5 (mobile-first). Goal-driven loop.

## GOAL (the loop is not finished until every line is true)
The owner and a NON-technical staff member can run the whole shop **from a phone** (360 px wide) as easily
as from a laptop: see what needs action first, answer a chat, approve a payment, pack and send an order —
with big, clear buttons, Burmese that is easy to read, and **no feature lost**.

Measured by the automated UI gate (U5) + all existing tests green + the owner test.

## How to work (loop engineering)
1. U0 first (audit + gate script), so every later change is measured.
2. Then one part at a time: change -> run FULL pytest -> run `scripts/ui_check.py` -> look at the screenshots
   yourself (Read the PNGs) -> fix -> repeat until both are 100% green and the screenshots look right.
3. Use the **frontend-design** skill for visual decisions (spacing, hierarchy, colour), inside Bootstrap.
4. Commit + push after each part. Deploy (restart web) after each part so the owner can look anytime.
5. Self-review against the GOAL at the end; fix gaps; loop again.
6. REPORT.md entry + OWNER TEST 4.15; PLAN.md NEXT TASK -> DONE.

## Hard limits (do not break)
- **No behaviour change.** Same routes, same forms, same field names, same CSRF, same HTMX attributes and
  targets, same permissions (owner vs staff), same i18n keys (`t()` / `tr()`), same Telegram rules.
- Existing tests: you may update a test ONLY where it checks HTML markup/CSS classes that changed; keep the
  same meaning (never delete an assertion about behaviour or permission). List every test change in REPORT.md.
- **Self-host** everything in app/web/static/vendor/ (no CDN: Myanmar connections are slow/blocked and the
  dashboard must work if a CDN is down): Bootstrap 5.3.x css+bundle js, Bootstrap Icons (font + css),
  a Burmese web font (Noto Sans Myanmar or Padauk, woff2, OFL licence; keep the licence file). Pin versions,
  note them in requirements/README.
- Keep HTMX 2.0.4. No React/Vue/build step. Jinja2 templates only. Small custom CSS on top (app.css).
- Screenshots and UI checks run ONLY against the test database with fake data — never the live DB
  (customer data). ui-shots/ goes in .gitignore.
- Keep page weight small: total CSS+JS per page under 400 KB (gzip not required to count).

## U0 Audit + gate (before changing any page)
- `scripts/ui_check.py` (Playwright, Python). If Chromium system libraries are missing, put the needed
  `sudo` line in REPORT.md and ask the owner once; until then run what you can.
  - Starts the app on a test DB with fixture data: products, customers, chats with long Burmese messages,
    carts, orders in every status, payment checks (incl. a 🧪 test one), learning cards, AI page data.
  - Logs in as owner AND as staff; visits EVERY page and main partial (list them from the router, so a new
    page can't be forgotten); languages en AND my; widths 360, 768, 1280.
  - Saves screenshots ui-shots/<page>-<role>-<lang>-<width>.png (git-ignored).
  - Checks (each a pass/fail line, exit 1 on any fail):
    C1 HTTP 200 and no JS console errors.
    C2 No horizontal page scroll (document scrollWidth <= viewport width + 1) at every width.
    C3 On 360 px every clickable button/link/input in main content is at least 40 px tall (tap size).
    C4 Every POST form has the CSRF field; HTMX requests still carry X-CSRF-Token.
    C5 Text contrast AA for body text and buttons (axe-core if it can be vendored offline; else a simple
       computed-colour check on buttons/badges/body).
    C6 Burmese pages: no text clipped (Burmese needs taller line-height; check elements' scrollHeight
       <= clientHeight on buttons, badges, nav items).
    C7 Feature inventory: every form action, button name/value and link that exists in the OLD templates
       exists in the new page for the same role (save the old inventory in U0 to tests/fixtures/ui_inventory.json).
- Write docs/ui-audit.md: the top problems you see in the old screenshots (keep it short).

## U1 Foundation
- base.html on Bootstrap: brand colour, consistent spacing, Bootstrap Icons next to text labels.
- **Phone navigation:** bottom tab bar (fixed) with the 5 daily items + counters: Inbox (Needs you),
  Chats, Payments, Orders, More. "More" opens an offcanvas with all other pages, language switch, logout.
  Laptop: top navbar with the same groups (daily items first, the rest under a "More" dropdown).
- Auto-reply ON/OFF switch: always visible, unmistakable colour (green ON / grey-red OFF), owner only to change.
- Flash messages -> Bootstrap toasts (still role="status"). Dangerous actions (reject payment, cancel order,
  clear test orders, edit locked order) -> Bootstrap confirm modal instead of browser confirm()/double click,
  with a no-JS fallback that still works.
- Burmese typography: the Burmese font for lang=my, line-height >= 1.8 for Burmese text, nothing clipped.
- Status colours used everywhere the same: cart grey, waiting payment amber, photo received blue,
  paid green, packed teal, sent out indigo, delivered dark green, cancelled red; 🧪 test = striped/purple badge.
- Optional if time: dark mode toggle (Bootstrap data-bs-theme), remembered per user.

## U2 Daily work pages (most important — the phone flow)
- **Inbox / Needs you:** a "Today" strip at the top: ⏰ customers waiting, payments to check, orders to pack,
  learning cards — each a big tappable card with a count. List items as cards on phone (customer, last
  message, intent/product chips, time ago, one main action button).
- **Chat page:** messenger-style bubbles (in left, out right, auto-reply marked 🤖), sticky reply box at the
  bottom on phone, quick-reply buttons as a horizontal scroll row, cart/order panel as an offcanvas on phone
  (button "🛒 Cart (n)") and a right column on laptop. Undo/"sending in n s" stays visible.
- **Payments:** card per check: big screenshot (tap to zoom), amount vs order total side by side with a clear
  ✅/⚠️, transaction ID field, big Approve (green) / Reject (with reason) buttons. 🧪 TEST banner stays.
- **Orders:** tabs/pills by status with counts; phone = cards, laptop = table; packing slip / next-status
  button per order.

## U3 Other pages
Products, Prices, Sales (keep charts readable on phone), Reports/Wanted, Learning, AI, Settings, Users,
Activity, Health, Practice, Help, Login (clean centred card, big inputs). Tables -> `table-responsive` on
laptop and stacked cards on phone where a table has more than 4 columns.

## U4 Speed + polish
- HTMX loading indicators (spinner on the clicked button, button disabled while sending).
- Empty states with a short friendly line (e.g. "No payments to check 🎉").
- Page titles per page; favicon.

## U5 The gate (must all pass to finish)
- Full pytest green (same count or more, nothing skipped that wasn't before).
- `scripts/ui_check.py` C1-C7 pass for every page × role × language × width.
- You looked at every 360 px screenshot and fixed anything ugly or confusing (say so in REPORT.md).
- Add tests/test_ui_check.py that runs ui_check in a quick mode (360 px, my + en, owner + staff, daily pages)
  so future epics can't break the phone layout.

## OWNER TEST 4.15 (write it in REPORT.md, simple steps)
On your PHONE browser (the dashboard link):
1. Log in. Bottom bar shows Inbox, Chats, Payments, Orders, More. Counts are right.
2. Switch to မြန်မာ: text easy to read, nothing cut off.
3. From the second Telegram account place an order and pay with the test code. On the phone: open the chat,
   open 🛒 Cart, go to Payments, approve. Customer gets the T-number confirmation.
4. Orders: move it packed -> sent out -> delivered with one tap each.
5. More -> every other page opens and nothing scrolls sideways.
6. Same on the laptop: everything you could do before is still there.
