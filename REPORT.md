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

## 2026-10-10 — Git push to GitHub (unblocked)
- Did: owner re-added the deploy key; pushed main (de6775f..6891923).
- Verified: `ssh -T` -> "Hi kaungkyaw3124/decant-inbox! You've successfully authenticated";
  `git status` shows main in sync with origin/main.
- Problems: GitHub API still reports `"visibility": "public"` and anonymous
  `git ls-remote` works, so the repo is NOT private yet.
- Needed from owner: Settings -> General -> Danger Zone -> Change visibility -> Private.

## 2026-10-10 — Step 1: firewall (ufw)
- Did: owner ran `~/hardening/step1-firewall.sh` (17:12 UTC): rollback armed, default
  deny incoming / allow outgoing, allow 22/tcp + in on tailscale0, removed 443/tcp,
  enabled ufw. Owner then cancelled the rollback timer and deleted the old 80/tcp rule.
- Verified: /etc/ufw/ufw.conf `ENABLED=yes`; fresh key login via port 10066 accepted
  at 17:12:38 (publickey); rollback timer gone; sshd still on 22; Postgres still
  127.0.0.1:5432 only.
- Old 10066/tcp rule: unused. All SSH connections arrive on internal port 22 (provider
  NAT rewrites 10066 -> 22) and nothing listens on 10066. Removal handed to owner:
  `sudo ufw delete allow 10066/tcp`; confirm in the Step 2 entry.
- Needed from owner: repo is still public (see previous entry).
