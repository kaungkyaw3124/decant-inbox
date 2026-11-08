# v5.6 — ONE simple Products page (replaces the Products / Prices / Stock tabs). Goal-driven loop.
Owner 2026-11-08: the 3 tabs are in 3 different places and the pages feel different. "Don't make complex, make the
user experience better and easy to use. Too many functions will confuse the user." So: FEWER things on screen.
Build after 5.5 (layout hotfix). Mockup (approved direction): docs/mockups/products-simple.dc.html.

## Rules for this epic (apply to every decision)
1. One page, one way to do each daily job, as few buttons as possible. If unsure, hide it under "More ▾".
2. Nothing is deleted: every function that exists today stays reachable (see "Where things go"), just not in the
   user's face. tests/fixtures/ui_inventory.json is updated with a note per moved control.
3. Plain words (EN + MY). No jargon. Units shown (Ks, ml).
4. The 5.5 layout rules apply (centred, full width, same pager/header pattern as the other pages).

## The page (/products)
- Title "Products", one-line subtitle ("21 perfumes · prices in Ks · click a perfume to edit it").
- Top right, only TWO buttons: primary **+ Add perfume**; secondary **More ▾** = Download prices (Excel), Upload
  prices (Excel, existing preview → Confirm flow), Upload first stock count (Excel), Empty vials (2/5/10 ml).
- ONE warning bar, only when needed: "2 perfumes need more stock: Aventus (low), Miss Dior (out) · Show only
  these" (click filters the list; click again to show all). No summary tiles, no filter tabs.
  (Stock value at cost, reorder list and stock history stay available: Settings → Inventory and the panel's
  "history" link; the owner's daily alert still lists low stock.)
- Search box (perfume, brand or nickname) + the standard pager (20 / 50 / 100).
- Table: **Perfume** (brand small, name bold) · **Prices** chips · **Stock** (badge In stock / Low / Out /
  Not tracked + "94.7 ml left" + thin bar) · **Nicknames** (number). Row click = open the side panel.
  "Messages" column is removed from this page (still on the product detail / Chats).

## Side panel (opens from the right; Esc or × closes; URL ?open=<id> so it can be linked / Back works)
Three tabs, one purpose each:
- **Prices:** 2 / 5 / 10 ml and Full-bottle price fields (labels above, units Ks) + ONE "Save prices". Staff may
  view; only the owner can save (staff see the numbers read-only with a lock note).
- **Stock:** big "94.7 ml left" + bar + "Can pour now: 2 ml ✓ 5 ml ✓ 10 ml ✓ Full bottle: none sealed". Two buttons:
  **+ Add bottle** (small form: size ml, how many, what it cost you; opens in the panel) and **Fix the amount**
  (type the real ml left + short reason). Link "See what changed (history)". Not tracked → one line "Stock for this
  perfume is not counted yet" + button **Start counting** (= Add bottle). In-stock flag for untracked perfumes:
  one switch "Available to sell" (the old manual flag).
- **Nicknames:** chips with ×, one input + Add, one-sentence explanation, "Customers wrote this N times · see
  messages". (The old Aliases wording becomes "Nicknames" everywhere.)
Bottle cost (for profit) is asked only in "Add bottle" and in the Excel price file; it is not a field on the
Prices tab.

## Where things go (nothing lost)
/prices (Excel price page) -> opens /products with the "Upload prices" dialog; /stock -> /products; stock Excel and
vial settings -> More ▾; reorder list + stock value + history + spill / low-stock thresholds -> Settings →
Inventory (one section, 5.4 pattern); product edit page (/products/<id>) -> the side panel (old URL redirects
to /products?open=<id>); "Add product" form -> the + Add perfume dialog (brand, name, 4 prices, nicknames optional).

## GOAL (loop until all true)
- **S1** Daily jobs in ≤ 3 clicks: change a price; add a received bottle; fix the ml; add a nickname; see what
  to reorder; add a perfume. Test each with Playwright (counts clicks) for owner, and "view only" for staff.
- **S2** The page shows ≤ 2 buttons + 1 optional bar above the table; the panel shows ≤ 2 buttons per tab.
  (ui_check rule: count visible buttons in the header region and the panel.)
- **S3** No function lost: ui_inventory lists every old control with its new place; every old URL redirects.
- **S4** Same look as the mockup at 1440 / 1920 px (centred, 5.5 rules); phone: list becomes cards, panel becomes a
  full-screen sheet; ui_check C1-C8 green for all roles, en + my.
- **S5** Full pytest + simulator green; stock maths unchanged (availability, packed deducts, undo returns) —
  the 5.1 tests must pass UNCHANGED.

## Loop
Build the page + panel -> redirect old URLs -> move the hidden functions -> run pytest + ui_check + click-count
test + screenshots vs the mockup -> fix the biggest difference / bug -> run again until S1-S5 are true. Do not
lower the goal, skip, delete or xfail tests. One line per loop in REPORT.md "5.6 scoreboard". Restart the web
service in the same step as each deploy. Stop only for something the owner must decide.

## OWNER TEST 5.6 (PC)
1. Products & prices -> one page, two buttons. Click "Stronger With You Intensely": Prices tab -> change 5 ml -> Save.
2. Stock tab -> + Add bottle (100 ml, cost) -> ml left goes up. Fix the amount to 90 -> shows 90.
3. Nicknames tab -> add "swy int" -> send "swy int 5ml" from your second account: the bot knows the perfume.
4. More ▾ -> Download prices, Upload prices (preview -> Confirm). Old links /prices and /stock still open the page.
5. Make some perfume low: the orange bar appears; "Show only these" filters.
