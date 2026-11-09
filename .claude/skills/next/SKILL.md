---
name: next
description: Pull the repo and do the task in PLAN.md "NEXT TASK" (written by the planning chat). Use when the owner types /next.
---
You are the builder for this project. The planning chat (claude.ai) writes your next job into
PLAN.md under "## NEXT TASK". Do it now:

1. Run `git pull --rebase`. Read CLAUDE.md, then PLAN.md, then the latest REPORT.md entry.
2. Find "## NEXT TASK" in PLAN.md.
   - If it is already marked DONE (or says `none`): look at "## QUEUE" in PLAN.md. Take the first item with
     Status TODO, copy it into "## NEXT TASK" (Status: TODO), mark it "moved to NEXT TASK" in the QUEUE,
     commit + push, and do it. If the QUEUE has no TODO item: say "No new task. Ask the planning chat for
     the next one." and stop.
   - If NEXT TASK is TODO but some of its work already exists uncommitted (git status), continue from it;
     never reset or stash it away.
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
7. KEEP GOING (owner 2026-11-03: "do them all"): if the QUEUE still has a TODO item, move it to NEXT TASK and
   start it right away in this same session — no need to wait for the owner to type /next. Stop only when the
   QUEUE is empty, when you need the owner (decision, sudo, login code, a secret), or when the usage limit stops you.
   Features that need an owner secret: build and test them with fakes, leave them OFF, list the missing value in
   REPORT.md, and continue with the next task.
8. Finish with a short summary for the owner in simple English: what changed, how to test it, and
   anything the owner must do (e.g. a value to put in .env — never print secrets).
Stop and ask the owner only if something needs their decision, a sudo command, a login code or a secret.
## ONE /next DOES THE WHOLE QUEUE (owner 2026-11-09: "I type /next once and it must do every job")
The owner must never have to type /next twice. Your turn must not end while there is still work:
- **Never end your turn (never write a final message) while a test suite, build or other background shell is
  running, or while a QUEUE item is still TODO.** A message like "I'll continue when the suite passes" ends the
  turn and the work silently stops until the owner types again. That is the bug to avoid.
- **Waiting for a long job:** start it in the background with output to a log and its PID in a file
  (`nice -n 19 pytest ... > /tmp/suite.log 2>&1 & echo $! > /tmp/suite.pid`), then BLOCK in the foreground, in
  a loop, until it ends: `timeout 590 tail --pid=$(cat /tmp/suite.pid) -f /dev/null; kill -0 $(cat /tmp/suite.pid)
  2>/dev/null && echo STILL_RUNNING || echo FINISHED` — repeat while it says STILL_RUNNING (each call waits up to
  ~10 minutes; the harness limit is 600 s). Or use the Monitor tool on the log with an until-loop. Do small
  useful work (next part, REPORT draft) while it runs, but come back and read the result yourself.
- When a task is DONE (REPORT.md written, PLAN.md marked DONE, pushed, deployed, web service restarted), look at
  the QUEUE at once and start the next TODO item in the same turn. Repeat until the QUEUE has no TODO item.
- The only reasons to stop: the QUEUE is empty; something needs the owner (a decision that cannot be undone, sudo,
  a login code, a secret); the usage limit. In those cases write the question in REPORT.md and PLAN.md
  "RESUME HERE" first, then stop with ONE clear sentence saying what you need.
- Keep PLAN.md "RESUME HERE" current after every part, so if the session is interrupted a fresh /next continues
  exactly there.
Arguments from the owner (optional): $ARGUMENTS
