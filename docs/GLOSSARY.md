# Glossary — the words the dashboard uses (docs/SPEC-v5.4-ui-ux-cleanup.md X5)

One word per thing, the same on every page. Burmese = the dashboard's own translation (app/web/i18n_my.py).
New labels: pick the plain word from this list; add a "?" popover (`ui.help`) when a word still needs explaining.
Units are always written: **Ks** (ကျပ်) for money, **ml** for sizes, **s** for seconds.

| English (dashboard) | မြန်မာ | Means | Instead of (do not use on staff pages) |
|---|---|---|---|
| Needs you | ကိုယ်တိုင်လုပ်ရန် | messages the app could not answer by itself | queue, inbox items |
| Auto-reply | အလိုအလျောက်ဖြေ | the app answers customers by itself | bot, automation |
| AI helper | AI အကူ | reads messages the rules are not sure about | model, LLM |
| Suggests only (SHADOW) | — | the AI fills in check cards, a person decides | shadow mode (only in the "?" text) |
| Acts when sure (AUTO) | — | the AI acts by itself when it is sure | auto mode (only in the "?" text) |
| Nicknames (Aliases) | နာမည်ပွားများ | other names customers use for a perfume | alias, normalized alias |
| Payments to check | စစ်ရန် ငွေလွှဲများ | payment screenshots waiting for a person | payment checks |
| Orders | အော်ဒါများ | paid orders to pack and send | — |
| Paid → Packed → Sent out → Delivered | ငွေချေပြီး → ထုပ်ပြီး → ပို့လိုက်ပြီ → ရောက်ပြီ | the order steps | statuses, states |
| Cancelled | ပယ်ဖျက်ပြီး | the order will not be sent | abandoned (only for old carts) |
| Stock | လက်ကျန် | what we can pour now, in ml | inventory levels |
| Price list | ဈေးစာရင်း | the Excel file with all prices | pricing sheet |
| Reply templates | အသင့်ဖြေစာများ | the ready texts the app sends | templates, placeholders |
| FAQ answers | FAQ အဖြေများ | answers to common questions | — |
| Payment methods | ငွေပေးနည်းများ | KPay / AYA accounts customers pay to | — |
| Learning | သင်ယူမှု | words the shop learned from you | patterns, rules |
| Test mode | စမ်းသပ်မုဒ် | test orders from the owner's second account | TEST_PAY_CODE (only under "Technical details") |
| Activity | လုပ်ဆောင်ချက် | who changed what, when | audit log |
| Customers | ဖောက်သည်များ | everyone who paid at least once | — |
| Reorder list | ပြန်မှာဖို့ စာရင်း | customers to remind about a new decant | — |
| Off-server backup | ဆာဗာအပြင် backup | an encrypted copy of the data outside the server | BACKUP_PASSPHRASE (only under "Technical details") |
| 2-step login | ၂ ဆင့် ဝင်ရောက်ခြင်း | password + a code from the phone app | TOTP |

Technical names (.env keys, model names, p50 / p90) appear only for the owner, inside a collapsed
"Technical details" line or on Health / AI helper, never on the daily pages (Chats, Orders, Payments).
