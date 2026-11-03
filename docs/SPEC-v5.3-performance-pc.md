# Epic 5.3 — Web app speed on the PC browser. Goal-driven loop.
Owner 2026-11-03: "loading takes long. Use cookies / let the browser keep things. Just focus on the computer"
(PC browser only: Chrome / Edge on Windows; no phone, no PWA in this epic). Same loop: measure -> fix the biggest
cause -> measure again -> repeat until the goal is met. Never weaken security.

## Planning chat finding (confirm in M0)
app/web/main.py `security_headers` sets `Cache-Control: no-store` on EVERY response, including /static
(Bootstrap, Inter + Noto Sans Myanmar fonts, icons, HTMX, app.css/js). So the browser downloads all of them again
on every page, through the Cloudflare tunnel. There is also no compression middleware.

## GOAL (measured from a PC browser through the public tunnel URL, not localhost)
- **P1** Page loads (Chats, Orders, Payments, Stock, Sales, Settings): second visit ≤ 1.0 s to usable
  (p90), first visit after login ≤ 2.5 s.
- **P2** Switching customer in the chat workspace ≤ 0.5 s (p90). Sending a reply shows in ≤ 0.3 s (optimistic).
- **P3** Server time for every page/partial ≤ 200 ms p90 (Server-Timing header).
- **P4** Repeat visit downloads ≤ 50 KB (static files from browser cache).
- **P5** Security unchanged or better: pages with customer data never stored by the browser or Cloudflare;
  CSP, CSRF, 2-step login, lockout unchanged; tests prove it.

## M0 Measure (keep it)
- Server-Timing header (db / render / total ms) on every response; slow-request log (> 300 ms) with route only.
- `scripts/perf_check.py`: Playwright Chromium (desktop 1440×900) against the tunnel URL (or a local
  cloudflared-like throttle profile: 150 ms RTT, 5 Mbps, if the tunnel is unreachable from the server):
  logs in, opens each main page cold + warm, switches 10 customers, sends a reply in the test chat;
  prints p50/p90, bytes, request count per page. REPORT.md: "before" numbers.
## M1 Browser cache for static files (biggest win)
- /static: `Cache-Control: public, max-age=31536000, immutable` with versioned URLs (file hash in the name or
  `?v=<hash>`, built at startup; templates use a `static_url()` helper so a changed file gets a new URL).
- HTML / partials / JSON with customer data: keep `Cache-Control: no-store` (private data never cached).
- Compression: gzip (or brotli) for HTML/CSS/JS/JSON ≥ 1 KB. Fonts: woff2 only, subset Noto Sans Myanmar and
  Inter to the needed ranges; `font-display: swap`; preload only the 2 fonts used above the fold.
## M2 Let the browser keep the page (no full reloads)
- The workspace shell (sidebar, CSS, JS, fonts) loads once; navigation and customer switches swap only the
  content area with HTMX (`hx-boost` / `hx-get` + `hx-push-url`, back/forward work, no-JS fallback keeps working).
- Prefetch on hover/focus for chat list rows and sidebar links (HTMX preload extension, vendored, ≤ 1 request
  per hover, never for POST/actions).
- Optimistic send: the bubble appears at once as "sending…", replaced when the outbox confirms; error → red retry.
## M3 Live updates instead of polling
- Server-Sent Events endpoint (auth required, same session checks) pushes "new message / status changed / needs
  you count" for the open workspace; the browser updates only that row/bubble. Polling stays as fallback.
## M4 Faster server
- EXPLAIN ANALYZE the slowest routes from M0; add missing indexes (Alembic migration); remove N+1 queries in
  templates; cache counters (needs-you, to pack, payments) in a small table/worker or 5 s in-memory cache.
- uvicorn: 2 workers if memory allows. Postgres: sensible memory settings for 4 GB.
- Claude Code's own test runs must not slow the live shop: run pytest/ui_check/simulator with `nice -n 19`
  `ionice -c3` and at most 1 xdist worker while the shop is live (document in CLAUDE-facing notes/REPORT).
## M5 Stay logged in on the owner's PC (secure "trusted device")
- On login with 2-step code: checkbox "Trust this computer for 30 days". Sets a separate cookie: random token
  (stored hashed in the DB with user, created, last used, user agent), `HttpOnly; Secure; SameSite=Lax;
  Path=/; Max-Age=30 days`. With it, an expired 12 h session is renewed silently; the 2-step code is skipped
  on that PC only; password still required after 30 days. Token rotates on use. "Log out everywhere" and
  My account → "Trusted computers" (list + remove) revoke it. Never store customer data in cookies or
  localStorage.
## M6 PC comfort
- Keyboard: ↑/↓ or J/K next/previous chat, Enter = send the suggested reply (when the composer is empty),
  Ctrl+Enter = send typed message, Esc = close panel, / = search. Shown in a "?" help popup.

## Tests
static headers immutable + versioned URLs change when the file changes; data pages no-store; compression on;
CSP still blocks inline; boosted navigation keeps CSRF + back/forward; prefetch never hits POST; SSE requires
login and only sends the user's allowed data; trusted-device cookie flags, hashing, rotation, revoke, expiry,
2-step skip only with a valid token; staff unaffected; full pytest + ui_check + simulator green;
perf_check meets P1-P4 (record numbers in REPORT.md each loop).

## OWNER TEST 5.3 (PC browser)
1. Log in, tick "Trust this computer". Open Chats, then Orders, then back: pages appear almost instantly.
2. Click through 10 customers: each opens in well under a second; arrow keys work.
3. Send a reply: the bubble appears immediately.
4. Close the browser, open tomorrow: still logged in (no code). My account → Trusted computers → remove → next
   visit asks for password + code again.
5. /health → Speed shows the page times.
