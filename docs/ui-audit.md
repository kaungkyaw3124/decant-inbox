# UI audit before v4.15 (old templates, 2026-10-31)

From `scripts/ui_check.py` on the old UI: 300 page views, **96 failed checks** (C2 sideways scroll: 22,
C3 tap size: 74; C1, C4, C5, C6 and C7 clean). Screenshots looked at for every daily page at 360 px.

Top problems:
1. **Navigation eats the phone screen.** 18 links + language + logout wrap into 6 lines at 360 px (≈ a third of
   the screen) before any content. No count for "Needs you"; Payments / Orders counts are tiny.
2. **Chat page scrolls sideways** on phones (564–628 px wide in 360 px; 1310–1374 px at 1280): the header card
   squeezes the name, the reply-kind tabs (Custom / Price / Cart list / …) do not wrap or scroll.
3. **Tables overflow** on phones: Orders (383–412 px), Users (398–429 px), Sales (364 px), Inbox in Burmese.
4. **Tap targets too small** (74 failures): "details" links, "?" help buttons (24 px), "Show test orders" link
   (16 px), checkboxes (21 px), tab links.
5. **Burmese:** no Burmese web font, so phones without a system Myanmar font show boxes; line-height 1.45 is
   tight for stacked Burmese vowels.
6. **Inbox on phones:** the Needs you box is very long, and each message row puts its action buttons in a narrow
   right column that squeezes the message text into a few characters per line.
7. Status colours differ between pages; dangerous actions (reject, cancel, clear test orders) rely on `<details>`
   or a second click with no clear warning.
