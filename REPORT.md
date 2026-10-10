# Report

Short entries from the VPS Claude Code session, newest last.

## 2026-10-10 — Login audit (Phase 0)
- Did: reviewed `who`/`w` and /var/log/auth.log.
- Verified: only two successful SSH logins ever (both `administrator`, password):
  45.125.5.23 (owner confirmed it's them) and 199.235.135.31. ~300 failed brute-force
  attempts from 7 IPs, none succeeded. No root logins.
- Problems: password auth is enabled; fixed in Step 2.

## 2026-10-10 — Step 0: rollback safety net
- Did: `~/hardening/rollback.sh` (disable ufw, remove sshd drop-in) and
  `~/hardening/step0-arm-rollback.sh` (installs it as root, fires in 10 min via systemd-run).
- Verified: scripts syntax-checked; armed at the start of each risky step.

## 2026-10-10 — Owner SSH key login test
- Verified: auth.log `Accepted publickey for administrator from 199.235.135.31`
  (ED25519 SHA256:IWs3D6dc…7ak) at 16:50 UTC via port 10066.

## 2026-10-10 — Git connected to GitHub (push BLOCKED)
- Did: `git init`, based on origin/main (de6775f), kept repo .gitignore and added
  `.claude/settings.local.json`; added `.env.example`; committed compose.yaml.
  Auth = repo deploy key `~/.ssh/decant_inbox_deploy` (SHA256:8srQeMXT…09c) via
  ssh alias `github-decant-inbox`.
- Verified: no .env / secrets / session / customer data staged.
- Problems: GitHub rejects the deploy key (`Permission denied (publickey)`), and the
  repo is still readable anonymously (API returns 200), so it is still PUBLIC.
- Needed from owner: add the deploy key to THIS repo with write access, and make it private.
