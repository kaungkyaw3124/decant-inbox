# Epic 4.7 — Shadow -> Auto graduation (owner decision 2026-10-17)

The owner asked to follow the planning chat's recommendation: keep the AI in SHADOW for
1-2 weeks with real customers, then switch to AUTO only if it is accurate enough. This epic
makes that automatic and measurable. Same "How to work" loop as docs/SPEC-v4.md.

## Rules (settings on /ai, owner only; defaults below)
- Graduation (SHADOW -> AUTO), checked once a day at 09:00 Asia/Yangon by the parser worker:
  - AI mode is SHADOW and "auto-graduate" is ON (default ON)
  - at least 7 days since SHADOW started (setting min_days = 7)
  - at least 50 decided AI suggestions in the window (accepted + corrected) (min_decisions = 50)
  - accuracy = accepted / (accepted + corrected) >= 95% over the last 14 days
  - ZERO corrections where the admin changed the AI's PRODUCT to a different product
    ("wrong product") in the last 14 days (changing size/qty/intent only = normal correction)
  - error rate (errors+rejected / calls) < 10% over the last 7 days
  -> switch to AUTO, audit_log actor "auto-graduation", Needs you notice
     "🧠 AI switched to AUTO: accuracy X% on N decisions, 0 wrong products".
  If not met: nothing changes; /ai shows "Graduation progress": days, decisions, accuracy,
  wrong products, errors, each ✅/⏳/❌, and what is missing.
- Safety brake (AUTO -> SHADOW), checked after every decided AI call and daily:
  - any admin correction of an AUTO-handled AI message that changes the product, OR
  - accuracy of the last 30 decided AI results < 90%, OR
  - error rate of the last 20 calls >= 50%
  -> back to SHADOW + Needs you notice with the reason. Graduation can happen again later
     (window restarts from the brake time).
- "Corrections" of AUTO-handled messages: on the message page an AUTO 🧠 result has a
  "🧠 AI was wrong" button -> opens the teaching card; saving it counts as corrected (and the
  normal undo/correction flow for the order applies).
- Owner can always switch manually; a manual switch turns auto-graduate OFF until turned on.

## Weekly AI summary in the repo (aggregates only, NO customer data)
- Every Monday 09:00 Yangon the worker writes reports/ai-weekly.md (overwrite) with:
  week, mode, calls, cost USD, avg latency, accepted, corrected, wrong products, accuracy,
  errors, auto-handled count, learned patterns approved/pending, graduation progress.
  No message text, no names, no phones. Commit + push it with the deploy key
  (message "AI weekly summary"), only that file. If push fails, log it and keep going.

## Acceptance tests
G1 7 days + 60 decisions + 97% + 0 wrong products + low errors -> AUTO, notice, audit.
G2 each missing condition (6 days / 40 decisions / 94% / 1 wrong product / 12% errors)
   -> stays SHADOW, progress shows which one.
G3 brake: product correction on an AUTO message -> SHADOW + notice; accuracy 88% on last 30
   -> SHADOW. Graduation window restarts after brake.
G4 manual switch disables auto-graduate.
G5 weekly summary contains only aggregate numbers (test scans for phone patterns, customer
   names, message texts used in the test) and is written for the right week.
