# Epic 5.0 — Go-live pack: alerts, off-server backup, safer login, packing slips. Goal-driven loop.
Same loop as 4.20/4.21: tests -> fix -> green -> deploy -> REPORT scoreboard; continue until the goal is met.
Features that need an owner secret are built and tested with fakes, then stay OFF until the owner sets the value.

## GOAL
- **L1** The owner learns about every important problem on his phone within 2 minutes, without opening the
  dashboard: service down, customer waiting > 5 min, payment to check, AI key refused / no credit, backup failed,
  disk > 85 %, tunnel URL changed (send the new URL).
- **L2** A copy of the database leaves the server every day, encrypted, and a restore from that copy is proven
  by a test.
- **L3** The dashboard login cannot be used with a stolen password alone (owner account: 2-step code).
- **L4** Packing an order takes one tap + one printed slip per order.

## G1 Alert bot (official Telegram Bot API, NOT the shop's personal account)
- Owner creates a bot with @BotFather and puts `ALERT_BOT_TOKEN=` and `ALERT_CHAT_ID=` in .env (REPORT.md
  explains how to get the chat id: send /start to the bot, then a helper script prints the id). Empty = OFF.
- New small service `decant-alerts` (systemd user unit, restart always) or a worker job; plain HTTPS to
  api.telegram.org; never uses the Telethon session; rate limit 20 alerts / hour, same alert at most once per
  30 min; "resolved" message when it is fixed.
- Alerts: the list in L1, plus a daily 21:00 summary (sales today, orders to pack, automatic %, AI cost).
  Numbers and names only; no customer message text unless the owner turns on "include message preview".
- Buttons in alerts (inline keyboard) only open the dashboard link (no actions from the bot in this epic).
- Settings page: on/off per alert type, test button "Send a test alert".
## G2 Off-server backup
- After the daily pg_dump: compress + encrypt (age or gpg symmetric with `BACKUP_PASSPHRASE` from .env) and send
  the file to the owner through the alert bot (sendDocument; Telegram bots allow up to 50 MB; if bigger, split
  into parts and say so). Keep 14 local copies as now.
- `scripts/restore_backup.py` + a test that encrypts, decrypts and restores a dump into a scratch database
  and compares row counts. REPORT.md: plain restore steps for the owner.
- Alert on failure. Passphrase never logged; tell the owner to save it in his password manager.
## G3 Safer login
- Owner account: TOTP 2-step code (authenticator app, QR on the settings page, 10 one-time recovery codes
  shown once). Staff: optional. Session timeout 12 h; "log out everywhere" button; login alert via G1 when a
  new device/IP logs in. Keep the existing lockout.
- `scripts/create_user.py --reset-2fa USER` for the owner (SSH) if the phone is lost.
## G4 Packing slip
- Orders: "Slip" per order and "Print all to pack": A6 / 80 mm receipt friendly HTML print page (Order ID big,
  name, phone, address, items with size and qty, total, paid/COD, a short thank-you line in Burmese), opens the
  browser print dialog. Optional: QR with the Order ID. Works from the phone (share/print).

## Tests
alert dedupe + rate limit + resolved; each alert trigger with fakes; backup encrypt/decrypt/restore round trip;
bot file split; TOTP enrol / login / recovery code / reset; staff unaffected; slip content + print CSS;
full suite + ui gate + simulator green.
## OWNER TEST 5.0
1. Create the bot, set the 3 .env values, restart; Settings → Send a test alert → arrives on your phone.
2. Stop the listener for 3 min (`systemctl --user stop decant-listener`) → alert; start it → "resolved".
3. Next morning: the encrypted backup file is in the bot chat. Run the restore steps on the scratch DB.
4. Turn on 2-step login; log out; log in with the code. Save the recovery codes.
5. Orders → Print all to pack → slips look right on paper / PDF.
