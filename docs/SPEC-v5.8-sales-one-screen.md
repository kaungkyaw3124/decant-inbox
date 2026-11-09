# v5.8 — Sales & profit on ONE screen (+ finish the 5.7 chat-speed follow-up). Goal-driven loop.
Owner 2026-11-09: the Sales page needs a redesign: no scrolling through three long tables; "one click and we
should see all the info". Approved demo: docs/mockups/sales-one-screen.dc.html (open it; match colours, sizes,
wording; the numbers in it are examples). Same rules as 5.6: few things on screen, nothing lost, plain words.

## The page (/sales) — fits a 1440×900 window with NO page scroll (7-day range, owner)
1. Header row: "Sales & profit" + one-line range text ("3 – 9 Nov 2026 · paid orders only · by the day they were
   paid (Yangon time)"); on the right the 5.7 date chips (Today · Yesterday · 7 days · 30 days · This month),
   "Pick dates…" and "Export Excel" (same /sales/export.xlsx). The old second row of buttons and the separate
   explanation paragraph are gone.
2. Four number boxes: **Revenue** (biggest, blue top line; "Average order N Ks"), **Profit** (green top line;
   "N% of revenue"), **Cost** ("perfume + vials"), **Orders** ("N items · N ml poured"). Staff see only Revenue and
   Orders (cost/profit hidden, as in 4.4); the grid then has 2 boxes.
3. ONE orange bar only when profit is incomplete: "Profit may look too high: N items have no cost yet." + the
   existing "Use today's costs for N orders" action (same POST /sales/fill-costs) and a link to Products.
4. **Per day** card (left, wide): legend (Revenue blue, Profit green) + segmented **Chart | Table**.
   Chart = paired bars per day with the revenue label above and weekday/date below (HTML bars, no chart library;
   tooltips with full numbers; ≤ 31 days shown, more days → weekly bars with a note). Table = the old Per-day
   table (Day, Orders, Qty, ml, Revenue, Cost, Profit, Total row). Remember the choice per user (small cookie).
5. **Per size** card (right): one row per size (2 ml, 5 ml, 10 ml, Full bottle…) with a revenue bar, "N Ks · N
   sold" and "profit N Ks".
6. **Per perfume** card (full width): top 6 by revenue with all old columns (Orders, Qty, ml, Revenue with a thin
   bar, Cost, Profit); link "Show all N perfumes" expands in place (no new page, no paging needed up to 100 rows,
   then the 5.4 pager). Staff: no Cost/Profit columns.
- Empty range: the cards show a friendly "No paid orders in this range" with the chips still usable; no layout jump.
- ml for "Full bottle" lines: keep the app's existing rule (whatever the current Sales page counts); do not change
  the maths in this epic. Totals must equal the old page's totals for the same range (test it).
- Burmese UI: all new labels in i18n_my.py; numbers and `ကျပ်` unit as today. Phone (< 768 px): boxes 2×2, cards
  stack, per-perfume table scrolls inside its card; no sideways page scroll.

## Part B — 5.7 follow-up (D2 was only partly met)
Chat-page server time p90 was still > 200 ms. Profile the chat route (Server-Timing from 5.3: db / render / total),
fix the biggest cost first (likely: queries that still run for all messages instead of the 20 shown, cart /
customer-panel queries, counters), until p90 ≤ 200 ms on the 600-message test customer. Record before/after in
REPORT.md.

## GOAL (loop until all true)
- **Z1** At 1440×900 and 1920×1080 the Sales page (owner, 7 days with data, and an empty range) needs no vertical
  scroll; at 1280×720 at most one short scroll. ui_check rule C9 measures it.
- **Z2** Every figure on the old page is still available (on screen or one click: Table, Show all). Totals,
  per-day, per-perfume and per-size numbers equal the old page for the same ranges (test with the existing sales
  fixtures; the existing sales tests pass UNCHANGED except markup selectors, listed in REPORT.md).
- **Z3** Looks like the mockup (screenshots 1440 / 1920 next to the mockup render) and follows the 5.5 layout rules
  (centred, same edges); staff view shows no cost / profit anywhere (HTML, tooltips, export unchanged).
- **Z4** ui_check C1-C9 green for owner + staff, en + my, phone + PC; full pytest green.
- **Z5** Part B: chat-page server p90 ≤ 200 ms.

## Loop
Build -> pytest + ui_check + screenshots vs mockup + totals-equal test + perf_check -> list failures / visible
differences -> fix the biggest -> run again until Z1-Z5 are true. Do not lower the goal, skip, delete or xfail
tests. One line per loop in REPORT.md "5.8 scoreboard". Restart the web service in the same step as each deploy.
Stop only for something the owner must decide.

## OWNER TEST 5.8 (PC)
1. Sales: the whole page is visible without scrolling. Click 7 days / 30 days / Today — numbers and bars change.
2. Per day: click Table, then Chart. Per perfume: click "Show all". Pick dates… works. Export Excel downloads.
3. If the orange bar shows, click "Use today's costs" — profit updates.
4. Log in as staff: only Revenue and Orders, no cost or profit anywhere.
5. Open a chat with a long history: it opens fast.
