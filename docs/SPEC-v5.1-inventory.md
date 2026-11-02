# Epic 5.1 — Stock in ml (inventory). Goal-driven loop.
New module app/inventory/ with its own tables (CLAUDE.md principle 6). Same loop; continue until the goal is met.

## GOAL
- **I1** The bot never sells what is not there: a size becomes "out of stock" automatically when the open
  bottle(s) of that perfume cannot fill it, and comes back when stock is added.
- **I2** Every packed order takes its ml (and empty vials) out of stock automatically; cancelling a packed order
  puts it back. Every change is in a history with who/why.
- **I3** The owner sees in one screen: ml left per perfume, bottles left, vials left, what to reorder, and the
  stock value at cost.
- **I4** Daily alert (5.0 bot, if on) for low stock.

## Data (Alembic)
- bottles(id, product_id, size_ml, remaining_ml, cost_mmk, status[sealed|open|empty], opened_at, note)
- vials(id, size_ml, count, cost_each_mmk) — empty decant vials/atomizers by size (2/5/10 ml)
- stock_moves(id, kind[purchase|decant|adjust|return|waste], product_id NULL, bottle_id NULL, vial_size NULL,
  ml_change, count_change, order_id NULL, user_id NULL, reason, created_at)
- settings: low-stock threshold per product (ml) and per vial size (count); spill/waste ml per decant (default 0.3 ml).

## Rules
- Available ml = open bottles' remaining + sealed bottles' size. A size is sellable when available ml ≥ size + waste
  and a vial of that size is in stock; full-bottle sale needs a sealed bottle.
- On "packed": take from the open bottle first (oldest opened), then open the next sealed bottle automatically
  (status open, opened_at). Not enough → block "packed" with a clear message (never negative stock).
- in_stock on the price list becomes automatic for products that have inventory; products without any bottles
  keep the manual in_stock flag (so the shop can start gradually).
- Bot replies use the same availability (4.17 size question lists only sellable sizes).

## Screens (in the 4.21 style)
- Products & prices → Stock tab: per perfume ml bar, bottles, sizes sellable, low-stock badge; actions: add bottle
  (purchase), open bottle, adjust (count / spill / gift) with reason, history.
- Vials: counts per size + add.
- Reorder list: below threshold, sorted by sales in the last 30 days; stock value at cost.
- Excel export/import of stock (same preview/confirm pattern as prices) for the first count.

## Tests
availability math; packed deducts + opens next bottle; cancel returns; blocked when short; vial deduction;
auto in_stock + bot size question respects stock; import preview; history; low-stock alert; simulator + full suite.
## OWNER TEST 5.1
1. Stock → import your first count (or add 1 bottle of SWY Intensely 100 ml, 20 vials of 5 ml).
2. Order SWY Intensely 5ml from the second account, pay (test code), mark packed → 94.7 ml left, 19 vials.
3. Set remaining to 3 ml → the bot now says 5ml/10ml are not available and offers 2ml.
4. Reorder list shows it; the daily alert lists it.
