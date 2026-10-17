# Epic 4.11 — Live test fixes (owner, 2026-10-17 09:25). Build AFTER 4.10.
Same "How to work" loop as docs/SPEC-v4.md.

## K1 "Form expired" (CSRF mismatch) loses the admin's work
Live: /messages/65/teach -> 403 "Form expired" (session csrf changed, e.g. a new login in the
same browser while an old page was open).
- On CSRF mismatch for a NORMAL (non-htmx) POST from a logged-in user: do NOT show an error
  page. Redirect back (303) to the page the form came from (safe same-site path from the form's
  `next`/Referer, never external) with a flash "ဒီစာမျက်နှာ သက်တမ်းကုန်သွားလို့ ပြန်ဖွင့်ပေးထားပါတယ်။
  ထပ်နှိပ်ပေးပါ။" and, for the teaching card, the admin's selections restored (pass them back as
  query/flash data; nothing is saved or sent). htmx requests: return HX-Refresh.
- Still never ACT on a mismatched token (security unchanged). Test: login twice -> old form ->
  redirected with selections kept, no DB change, no outbox row.

## K2 One message, several actions (remove + add)
Live: "Y edp မယူတော့ဘူး ဗျ liquid brun 10 ml ယူပါမယ်" (cart had Y EDP 10ml) = remove Y EDP AND
want liquid brun (not sold). AI understood; the card allowed only ONE intent.
- Parser + AI: items carry their own action: add | remove (| ask_price). Split clauses on
  ဗျ/နော်/ပြီးတော့/နဲ့/, ။ and the action words (မယူတော့ဘူး/ဖြုတ် = remove; ယူမယ်/ယူပါမယ်/ထည့် = add).
  Message intent = "modify_cart" when it has both adds and removes.
- AI schema: items[].action (add|remove|ask_price). Checker: remove only for products in the cart.
- Teaching card: one row per item with its own action buttons (➕ ယူမယ် / ➖ ဖြုတ်မယ် / 💬 ဈေးမေး)
  and the product question for unknown items (incl. 🚫 မရှိဘူး).
- Result: apply removes and adds together, ONE reply: new list + total + not-stocked lines +
  next step / resume line (and payment info again if waiting_payment and total changed, 4.10).
- Auto mode may do this automatically when every item is certain (rules exact or AI >= threshold).
Tests: the live sentence (rules path and AI path, SHADOW card and AUTO), remove+add known,
remove product not in cart -> card, paid order -> locked (4.10).

## K3 Learn box must propose only reusable phrases
Live: proposed learning the whole sentence "y edp မယူတော့ဘူး ဗျ liquid brun ယူပါမယ်".
- Propose ONLY: unknown product names (nickname / not_stocked) and short intent phrases
  (<= 4 words, no product names, no numbers/sizes, no particles-only like ဗျ/နော်).
- Never propose a phrase that is already known (seed keyword or approved pattern) or a whole
  multi-clause sentence. If nothing qualifies, hide the learn box.
- One checkbox per proposed pattern (not one for the whole sentence).
Tests: the live sentence proposes only "liquid brun" (not_stocked) — "မယူတော့ဘူး"/"ယူပါမယ်" are
already known so not proposed; "ysl edp ရောယူပါမယ်" proposes "ysl edp" (+ "ရောယူပါမယ်" only if unknown).

## K4 Stale items in Needs you
Live: "ysl edp 10 ml ရောယူပါမယ်" still listed after 32 h although the chat moved on.
- A Needs-you item (teaching card / unanswered) older than 24 h whose customer has sent a NEWER
  message that was handled (or has its own Needs-you item) moves to a collapsed "Older (n)"
  section. Payments to check are NEVER moved.
- "Dismiss all older" (owner + staff) marks them ignored (audit_log). Undo 60 s.
- Count badge shows only current items.
Tests: aging + newer message -> Older; payment never Older; dismiss + undo; badge counts.

At the end: short OWNER TEST for K1-K4 in REPORT.md.
