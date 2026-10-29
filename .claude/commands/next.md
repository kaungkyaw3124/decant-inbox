---
description: Pull the repo and do the task in PLAN.md "NEXT TASK" (written by the planning chat)
---
You are the builder for this project. The planning chat (claude.ai) writes your next job into
PLAN.md under "## NEXT TASK". Do it now:

1. Run `git pull --rebase`. Read CLAUDE.md, then PLAN.md, then the latest REPORT.md entry.
2. Find "## NEXT TASK" in PLAN.md.
   - If it says `none` or `waiting`, or it is already marked DONE: say "No new task. Ask the planning chat
     for the next one." and stop.
   - If a spec file is named there, read it fully before starting.
3. Do the task with the loop (unless the task says otherwise):
   a. Implement one part at a time.
   b. Write its acceptance tests (pytest; fake Telegram client for chat flows).
   c. Run the FULL suite. On failure: find the cause, fix the CODE, run again. Loop until 100% green.
      Never skip, delete or xfail a test to get green. Change a test only if it contradicts the spec.
   d. Before any migration: back up the database; test migration down/up.
   e. Self-review against the goal: every acceptance item has a test that would fail if it broke.
   f. Commit + push after each part. Before every commit check that .env, secrets/, *.session and
      customer data are NOT staged.
4. Deploy: restart the affected services, check /healthz and `bash scripts/status.sh`.
5. Write the REPORT.md entry: what was built, decisions, test counts, and an OWNER TEST SCRIPT
   (exact messages to send from the second Telegram account + exact dashboard clicks + expected results).
6. In PLAN.md: under "## NEXT TASK" change the status line to `Status: DONE <date> — see REPORT.md`,
   update the Status table and "RESUME HERE". Commit + push.
7. Finish with a short summary for the owner in simple English: what changed, how to test it, and
   anything the owner must do (e.g. a value to put in .env — never print secrets).
Stop and ask the owner only if something needs their decision, a sudo command, a login code or a secret.
Arguments from the owner (optional): $ARGUMENTS
