"""Burmese dashboard texts (docs/SPEC-v4.md 4.5). Key = the English text, value = Burmese.

"{name}" parts are filled in (templates) or matched (texts built in Python, see i18n.py).
tests/test_v4_i18n.py checks that every t("...") in the templates has an entry here.
Words kept as they are on purpose: product names, ml, ကျပ်, KPay / AYA, FAQ, ID, Telegram, Excel.
"""

# enum values shown in the dashboard (intents, statuses, roles, audit groups)
CODES = {
    # intents
    "buy": "ဝယ်မယ်", "ask_stock": "ရှိလားမေး", "ask_price": "ဈေးမေး", "other": "အခြား", "unknown": "မသိ",
    "remove": "ဖြုတ်မယ်", "confirm": "အတည်ပြု", "address": "လိပ်စာ", "ask_delivery": "ရောက်ပြီလားမေး",
    "cancel_order": "အော်ဒါပယ်", "greeting": "နှုတ်ဆက်", "previous_item": "အရင်ကဟာ", "question": "မေးခွန်း",
    "ignore": "ဘာမှမလုပ်", "change_info": "လိပ်စာ/ဖုန်း ပြောင်း", "payment_sent": "ငွေလွှဲပြီး (ပုံမပါ)", "modify_cart": "ဖြုတ်ပြီး ထည့်",
    # message review
    "new": "အသစ်", "done": "ပြီးပြီ", "ignored": "လျစ်လျူရှုထား",
    # orders
    "cart": "ခြင်း", "confirmed": "အတည်ပြုပြီး", "waiting_payment": "ငွေစောင့်နေ", "photo_received": "ငွေလွှဲပုံရပြီ",
    "paid": "ငွေရပြီ", "packed": "ထုပ်ပြီး", "sent_out": "ပို့လိုက်ပြီ", "delivered": "ရောက်ပြီ",
    "cancelled": "ပယ်ဖျက်ပြီး", "abandoned": "ပစ်ထားတဲ့ခြင်း",
    # payment checks
    "pending": "စစ်ရန်", "several": "ပုံအများကြီး", "approved": "အတည်ပြုပြီး", "rejected": "ငြင်းပယ်ပြီး",
    "not_payment": "ငွေလွှဲမဟုတ်",
    # parse methods, roles
    "rules": "စည်းမျဉ်း", "human": "လူ", "ai": "AI", "owner": "ပိုင်ရှင်", "staff": "ဝန်ထမ်း",
    # audit log groups (Activity page)
    "quick": "တစ်ချက်နှိပ်", "auto": "🤖 အလိုအလျောက်", "payment": "ငွေစစ်", "order": "အော်ဒါ", "learning": "သင်ယူမှု",
    "user": "အသုံးပြုသူ", "product": "ပစ္စည်း", "outbox": "စာပို့", "faq": "FAQ", "prices": "ဈေးနှုန်း",
    "sales": "အရောင်း", "media": "ဓာတ်ပုံ", "review": "စစ်ပြီး", "customer": "ဖောက်သည်", "alias": "နာမည်ပွား",
    "parse": "ပြင်ဆင်", "settings": "ဆက်တင်", "template": "စာပုံစံ", "needs_you": "ကိုယ်တိုင်လုပ်ရန်",
    "message": "စာ", "payment_method": "ငွေပေးနည်း", "reply_template": "အသင့်ဖြေစာ", "order_rules": "အော်ဒါ ဆက်တင်",
    "vial_costs": "ပုလင်းသေး ကုန်ကျစရိတ်",
    # AI calls (docs/SPEC-v4.6-ai.md)
    "shadow": "🧠 အကြံပြုထား", "accepted": "✅ လက်ခံ", "corrected": "✏️ ပြင်ပြီး", "error": "⚠️ အမှား",
    "cap": "တစ်ရက် အကန့်အသတ်ပြည့်", "budget": "လစဉ် ဘတ်ဂျက်ကုန်", "unused": "မသုံး",
}

MY = {
    # ---------- header, menus, common words ----------
    "Inbox": "စာဝင်", "Payments": "ငွေစစ်ရန်", "Orders": "အော်ဒါများ", "Chats": "စကားပြောများ",
    "Products": "ပစ္စည်းများ", "Prices": "ဈေးနှုန်းများ", "Sales": "အရောင်း", "Reports": "စာရင်းချုပ်",
    "Learning": "သင်ယူမှု", "Settings": "ဆက်တင်", "Users": "အသုံးပြုသူများ", "Health": "စနစ်အခြေအနေ",
    "Practice": "လေ့ကျင့်ခန်း", "Help": "အကူအညီ", "Log out": "ထွက်မယ်", "Log in": "ဝင်မယ်",
    "Auto-reply": "အလိုအလျောက်ဖြေ", "ON": "ဖွင့်ထား", "OFF": "ပိတ်ထား",
    "Click to turn auto-reply OFF": "နှိပ်ရင် အလိုအလျောက်ဖြေတာ ပိတ်မယ်",
    "Click to turn auto-reply ON": "နှိပ်ရင် အလိုအလျောက်ဖြေတာ ဖွင့်မယ်",
    "Switch the dashboard to English": "Dashboard ကို အင်္ဂလိပ်လို ပြောင်းမယ်",
    "Switch the dashboard to Burmese": "Dashboard ကို မြန်မာလို ပြောင်းမယ်",
    "Error": "အမှား", "Back": "နောက်သို့", "Customer": "ဖောက်သည်", "Customers": "ဖောက်သည်",
    "Done": "ပြီးပြီ", "done": "ပြီးပြီ", "Ignore": "လျစ်လျူရှု", "ignore": "လျစ်လျူရှု", "Undo": "↩ ပြန်ဖျက်",
    "Save": "သိမ်းမယ်", "save": "သိမ်းမယ်", "Cancel": "မလုပ်တော့ဘူး", "Delete": "ဖျက်မယ်", "delete": "ဖျက်မယ်",
    "Add": "ထည့်မယ်", "Edit": "ပြင်မယ်", "Send": "ပို့မယ်", "Show": "ပြမယ်", "Apply": "ပြမယ်", "Next": "နောက်တစ်ဆင့်",
    "Search": "ရှာမယ်", "Filter": "စစ်ထုတ်မယ်", "Reset": "အစကပြန်", "Status": "အခြေအနေ", "Note": "မှတ်ချက်",
    "Name": "နာမည်", "Brand": "အမှတ်တံဆိပ်", "Product": "ပစ္စည်း", "product": "ပစ္စည်း", "Size": "ဆိုဒ်",
    "Qty": "အရေအတွက်", "Quantity": "အရေအတွက်", "Total": "စုစုပေါင်း", "Price": "ဈေး", "Phone": "ဖုန်း",
    "Phones": "ဖုန်းများ", "Address": "လိပ်စာ", "Cart": "ခြင်း", "Chat": "စကားပြော", "Message": "စာ",
    "Messages": "စာများ", "When": "အချိန်", "Who": "ဘယ်သူ", "What": "ဘာလုပ်", "Details": "အသေးစိတ်", "By": "လုပ်သူ",
    "by": "လုပ်သူ", "You": "ကိုယ်", "Photo": "ဓာတ်ပုံ", "Newer": "အသစ်များ", "Older": "အဟောင်းများ",
    "Nothing yet.": "ဘာမှ မရှိသေးပါ။", "No messages.": "စာ မရှိပါ။", "yes": "ရှိ", "no": "မရှိ", "none": "မရှိ",
    "e.g.": "ဥပမာ", "auto": "အလိုအလျောက်", "Contents": "မာတိကာ", "Language": "ဘာသာစကား",
    "Username": "အသုံးပြုသူအမည်", "Password": "စကားဝှက်", "Active": "အသုံးပြုနေ", "active": "အသုံးပြုနေ",
    "inactive": "မသုံးတော့", "edited": "ပြင်ထား", "approved": "အတည်ပြုပြီး", "Approve": "အတည်ပြုမယ်",
    "Reject": "ငြင်းမယ်", "remove": "ဖယ်မယ်", "Remove": "ဖယ်မယ်", "Words": "စာလုံး", "Means": "အဓိပ္ပာယ်",
    "waiting": "စောင့်နေ", "Try again": "ထပ်ကြိုးစားမယ်", "Dismiss": "ဖျောက်မယ်", "Open chat": "စကားပြော ဖွင့်မယ်",
    "open chat": "စကားပြော ဖွင့်မယ်", "details": "အသေးစိတ်", "Start": "စမယ်", "Finish": "ပြီးပြီ", "Score": "အမှတ်",
    "full": "ပုလင်းလိုက်", "full bottle": "ပုလင်းလိုက်", "Full bottle": "ပုလင်းလိုက်", "the full bottle": "ပုလင်းလိုက်",
    "Today": "ဒီနေ့", "Yesterday": "မနေ့က", "This week": "ဒီအပတ်", "This month": "ဒီလ", "Custom": "ကိုယ်တိုင်ရေး",

    # ---------- inbox, Needs you ----------
    "Needs you": "ကိုယ်တိုင်လုပ်ရန်", "Nothing waiting for you.": "လုပ်စရာ မရှိပါ။",
    "several photos — ask for one": "ပုံအများကြီး — တစ်ပုံပဲ ပို့ခိုင်းပါ",
    "payment screenshot to check": "စစ်ရန် ငွေလွှဲ screenshot", "wants to cancel a paid order": "ငွေချေပြီး အော်ဒါကို ပယ်ချင်တယ်",
    "payment photo sent": "ငွေလွှဲပုံ ပို့ပြီး", "Cancel order": "အော်ဒါ ပယ်ဖျက်မယ်",
    "Money may be involved: refund outside the system.": "ငွေပါနိုင်တယ် — ငွေပြန်အမ်းတာ စနစ်ပြင်ပမှာ လုပ်ပါ။",
    "Send “order cancelled”": "“အော်ဒါပယ်ပြီ” စာ ပို့မယ်", "Send nothing": "ဘာမှ မပို့ဘူး",
    "keep order (done)": "အော်ဒါ ဆက်ထားမယ် (ပြီးပြီ)", "no payment for {hours} h": "{hours} နာရီ ငွေမလွှဲသေး",
    "Send payment reminder": "ငွေလွှဲရန် သတိပေးစာ ပို့မယ်", "Cancel order + tell them": "အော်ဒါ ပယ်ပြီး ပြောပြမယ်",
    "price needed": "ဈေး လိုတယ်", "Price (ကျပ်)": "ဈေး (ကျပ်)", "Bottle ml": "ပုလင်း ml", "Bottle size": "ပုလင်း ဆိုဒ်",
    "Save + send list": "သိမ်းပြီး စာရင်းပို့မယ်",
    "When the owner adds the price, the list goes out by itself.": "ပိုင်ရှင် ဈေးထည့်ရင် စာရင်း အလိုအလျောက် ပို့မယ်။",
    "{n} patterns to approve": "အတည်ပြုရန် သင်ထားတာ {n} ခု", "{n} pattern to approve": "အတည်ပြုရန် သင်ထားတာ {n} ခု",
    "taught differently — decide on the Learning page": "မတူအောင် သင်ထားတယ် — သင်ယူမှု စာမျက်နှာမှာ ဆုံးဖြတ်ပါ",
    "resolve": "ဖြေရှင်းမယ်", "unanswered": "မဖြေရသေး", "Send FAQ": "FAQ အဖြေ ပို့မယ်", "also asks": "ဒါလည်း မေးတယ်",
    "reply not sent": "စာ မပို့ရသေး", "new message while paused": "ခဏရပ်ထားတုန်း စာအသစ်ဝင်",
    "you replied by hand; auto off until {time}": "ကိုယ်တိုင်ဖြေထားလို့ {time} အထိ အလိုအလျောက်ဖြေတာ ပိတ်ထား",
    "order cancelled automatically (not paid)": "ငွေမလွှဲလို့ အော်ဒါ အလိုအလျောက် ပယ်ပြီး",
    "Handled automatically (last 24 h)": "အလိုအလျောက် ဖြေပြီး (နောက်ဆုံး ၂၄ နာရီ)",
    "cancelled": "ပယ်ဖျက်ပြီး", "sent": "ပို့ပြီး", "failed": "မပို့နိုင်", "sending…": "ပို့နေတယ်…",
    "price reply": "ဈေးပြန်ပြော", "added to cart + list": "ခြင်းထဲထည့် + စာရင်း", "removed + list": "ဖယ် + စာရင်း",
    "cart list": "ခြင်းစာရင်း", "phone/address": "ဖုန်း/လိပ်စာ", "address": "လိပ်စာ",
    "we don't have it": "မရှိဘူးလို့ ပြော", "delivery status": "ပို့ဆောင်မှု အခြေအနေ", "order cancelled": "အော်ဒါ ပယ်ပြီး",
    "FAQ answer": "FAQ အဖြေ", "greeting": "နှုတ်ဆက်စာ", "asked which earlier item": "အရင်ကဟာ ဘယ်ဟာလဲ မေးပြီး",
    "added + cart list": "ထည့် + ခြင်းစာရင်း", "removed + cart list": "ဖယ် + ခြင်းစာရင်း", "confirmed": "အတည်ပြုပြီး",
    "address saved": "လိပ်စာ သိမ်းပြီး", "phone/address saved": "ဖုန်း/လိပ်စာ သိမ်းပြီး", "taught": "သင်ပေးပြီး",
    "{what} sent": "{what} ပို့ပြီး", "not sent": "မပို့ရ", "Sending in {n} s": "{n} စက္ကန့်အတွင်း ပို့မယ်",
    "Edit before send": "မပို့ခင် ပြင်မယ်", "Address to save (you can fix it first)": "သိမ်းမယ့် လိပ်စာ (အရင်ပြင်လို့ရ)",
    "Search text or customer": "စာ (သို့) ဖောက်သည် ရှာမယ်", "Any status": "အခြေအနေ အားလုံး", "Intent": "လိုချင်တာ",
    "Requests (not “other”)": "မေးတာ/ဝယ်တာ (“အခြား” မပါ)", "All intents": "အားလုံး", "Any product": "ပစ္စည်း အားလုံး",
    "Needs review": "စစ်ဖို့ လိုတာ", "Ignored customers": "လျစ်လျူရှုထားတဲ့ ဖောက်သည်",
    "No messages match these filters.": "ဒီအတိုင်း ရှာတာ စာ မတွေ့ပါ။",
    "Messages the app could not answer by itself. Work from top to bottom; each line says what to do.":
        "App က ကိုယ်တိုင် မဖြေနိုင်တဲ့ စာတွေ။ အပေါ်ကနေ အောက်ကို လုပ်ပါ — စာကြောင်းတိုင်းမှာ ဘာလုပ်ရမလဲ ပြထားတယ်။",
    "All messages, newest first. Done and Ignore hide a message from the “New” list; Undo brings it back.":
        "စာအားလုံး၊ အသစ်ဆုံး အပေါ်မှာ။ “ပြီးပြီ” နဲ့ “လျစ်လျူရှု” နှိပ်ရင် “အသစ်” စာရင်းက ပျောက်မယ်၊ “ပြန်ဖျက်” နှိပ်ရင် ပြန်ပေါ်မယ်။",
    "Product taken from the customer’s previous message": "ဖောက်သည်ရဲ့ အရင်စာက ပစ္စည်း",
    "from previous message": "အရင်စာထဲက", "not parsed yet": "မဖတ်ရသေး", "needs review": "စစ်ဖို့ လို",

    # ---------- message page ----------
    "Open chat and reply": "စကားပြော ဖွင့်ပြီး ဖြေမယ်", "Normalized": "ပြင်ညှိထားတဲ့စာ", "confidence": "သေချာမှု",
    "Not in your product list": "ပစ္စည်းစာရင်းထဲ မရှိ",
    "Resolve each item; then the reply continues by itself (auto-reply ON) or the one-tap button appears.":
        "ပစ္စည်းတစ်ခုချင်း ဖြေရှင်းပါ — ပြီးရင် အလိုအလျောက် ဆက်ဖြေမယ် (သို့) တစ်ချက်နှိပ် ခလုတ် ပေါ်လာမယ်။",
    "Contains the nickname of {name}, plus other words: is it the same perfume?":
        "{name} ရဲ့ နာမည်ပါပေမယ့် တခြားစာလုံးတွေလည်း ပါတယ် — ဒီရေမွှေးပဲလား?",
    "It's in my list: choose…": "စာရင်းထဲ ရှိတယ် — ရွေးပါ…", "Most similar": "အနီးစပ်ဆုံး", "All products": "ပစ္စည်း အားလုံး",
    "Save as alias": "နာမည်ပွားအဖြစ် သိမ်းမယ်", "New product": "ပစ္စည်းအသစ်",
    "Price for {what} (ကျပ်)": "{what} ဈေး (ကျပ်)", "Bottle size (ml)": "ပုလင်း ဆိုဒ် (ml)", "{size}ml price": "{size}ml ဈေး",
    "Full bottle price": "ပုလင်းလိုက် ဈေး", "In stock": "ပစ္စည်းရှိ", "Add product + price": "ပစ္စည်းနဲ့ ဈေး ထည့်မယ်",
    "We don't have it": "ဒီပစ္စည်း မရှိဘူး", "Resolved": "ဖြေရှင်းပြီး", "alias": "နာမည်ပွား", "new product": "ပစ္စည်းအသစ်",
    "Quick reply": "အမြန်ဖြေ", "Sent {n} s after the tap; you can undo until then.":
        "နှိပ်ပြီး {n} စက္ကန့်နေရင် ပို့မယ် — အဲဒီအထိ ပြန်ဖျက်လို့ရတယ်။",
    "Marks this message done.": "ဒီစာကို ပြီးပြီလို့ မှတ်မယ်။", "Mark {status}": "“{status}” လို့ မှတ်မယ်",
    "Back to new": "အသစ်ကို ပြန်ထား", "Correct the parse": "App နားလည်တာ ပြင်မယ်", "Size (ml)": "ဆိုဒ် (ml)",
    "This message has {n} items; saving a correction keeps only this one.":
        "ဒီစာထဲ ပစ္စည်း {n} ခု ပါတယ် — ပြင်ပြီး သိမ်းရင် ဒီတစ်ခုပဲ ကျန်မယ်။",
    "Save as alias (optional): the words in this message that name the product":
        "နာမည်ပွားအဖြစ် သိမ်းမယ် (မထည့်လည်းရ) — ဒီစာထဲက ပစ္စည်းနာမည် စာလုံး",
    "Save correction": "ပြင်တာ သိမ်းမယ်",
    "Ignored: their messages are hidden from the inbox (still saved).":
        "လျစ်လျူရှုထား — သူ့စာတွေ စာဝင်မှာ မပြဘူး (သိမ်းတော့ သိမ်းထားတယ်)။",
    "Stop ignoring": "လျစ်လျူမရှုတော့ဘူး",
    "Ignore this customer (friends, family, spam)": "ဒီလူကို လျစ်လျူရှုမယ် (သူငယ်ချင်း၊ မိသားစု၊ spam)",
    "Parse history": "App နားလည်ခဲ့တာ မှတ်တမ်း", "Conf.": "သေချာမှု",
    "Answer the questions: the app finishes this customer’s request and remembers the answer for next time.":
        "မေးခွန်းတွေ ဖြေပါ — App က ဒီဖောက်သည်ကို ဆက်ဖြေပေးပြီး နောက်တစ်ခါအတွက် မှတ်ထားမယ်။",
    "The app made this reply. Read the preview; if it is right, tap the button. You have a few seconds to Undo.":
        "ဒီစာကို App က ရေးထားတယ်။ အရင်ဖတ်ပါ — မှန်ရင် ခလုတ်နှိပ်ပါ။ နှိပ်ပြီး စက္ကန့်အနည်းငယ်အတွင်း ပြန်ဖျက်လို့ရတယ်။",
    "Only if the app understood the message wrong: choose what the customer really wants and save.":
        "App နားလည်တာ မှားမှပဲ သုံးပါ — ဖောက်သည် တကယ်လိုချင်တာ ရွေးပြီး သိမ်းပါ။",

    # ---------- chats, chat, thread, cart ----------
    "ignored": "လျစ်လျူရှုထား", "Open in Telegram": "Telegram မှာ ဖွင့်မယ်", "Allow auto-reply": "အလိုအလျောက်ဖြေတာ ခွင့်ပြုမယ်",
    "Never auto-reply to this customer": "ဒီလူကို ဘယ်တော့မှ အလိုအလျောက် မဖြေနဲ့",
    "Auto-reply is off for this customer.": "ဒီဖောက်သည်အတွက် အလိုအလျောက်ဖြေတာ ပိတ်ထားတယ်။",
    "Paused — you're replying by hand (until {time}).": "ခဏရပ်ထား — ကိုယ်တိုင် ဖြေနေတယ် ({time} အထိ)။",
    "Resume auto": "အလိုအလျောက် ပြန်ဖွင့်မယ်", "View": "ကြည့်ပုံ", "Reply type": "ဖြေစာ အမျိုးအစား",
    "Cart list": "ခြင်းစာရင်း", "Ask phone": "ဖုန်းမေး", "Ask address": "လိပ်စာမေး", "Payment info": "ငွေလွှဲရန် အချက်အလက်",
    "This customer has never messaged us, so we can't message them.": "ဒီလူက ကိုယ့်ဆီ စာမပို့ဖူးလို့ စာပို့လို့ မရပါ။",
    "all sizes": "ဆိုဒ် အားလုံး", "Make price reply": "ဈေးစာ ရေးမယ်",
    "Pre-filled from what the customer asked in the last 24 h.": "နောက်ဆုံး ၂၄ နာရီအတွင်း ဖောက်သည်မေးတာကနေ ဖြည့်ထားတယ်။",
    "Message (you can edit it)": "စာ (ပြင်လို့ရတယ်)",
    "Starts with the greeting: we haven't messaged them in the last 6 hours.":
        "နှုတ်ဆက်စာနဲ့ စမယ် — နောက်ဆုံး ၆ နာရီအတွင်း စာမပို့ရသေးလို့။",
    "Write your own reply, or pick a ready reply (price, cart list, ask phone…). You can edit it before Send.":
        "ကိုယ်တိုင်ရေးပါ (သို့) အသင့်စာ ရွေးပါ (ဈေး၊ ခြင်းစာရင်း၊ ဖုန်းမေး…)။ မပို့ခင် ပြင်လို့ရတယ်။",
    "Show ignored customers": "လျစ်လျူရှုထားတဲ့ ဖောက်သည်တွေ ပြမယ်", "sticker / file": "စတစ်ကာ / ဖိုင်",
    "waiting for reply": "ပြန်ဖြေဖို့ စောင့်နေ", "No chats yet.": "စကားပြော မရှိသေးပါ။",
    "Every customer conversation, latest first. “waiting for reply” = the customer wrote last.":
        "ဖောက်သည်တိုင်းနဲ့ စကားပြောတာ၊ နောက်ဆုံး အပေါ်မှာ။ “ပြန်ဖြေဖို့ စောင့်နေ” = ဖောက်သည်က နောက်ဆုံး ရေးထားတာ။",
    "several photos sent together": "ပုံအများကြီး တစ်ခါတည်း ပို့ထား", "Photo from the chat": "စကားပြောထဲက ဓာတ်ပုံ",
    "Loading photo…": "ဓာတ်ပုံ ဖွင့်နေတယ်…", "Could not load": "မဖွင့်နိုင်ပါ", "Show photo": "ဓာတ်ပုံ ပြမယ်",
    "sticker, voice or file — open Telegram to see it": "စတစ်ကာ၊ အသံ (သို့) ဖိုင် — Telegram မှာ ဖွင့်ကြည့်ပါ",
    "Sent by auto-reply": "အလိုအလျောက် ပို့ထားတာ", "queued": "ပို့ဖို့ တန်းစီထား",
    "unknown: check Telegram whether it arrived": "မသေချာ — ရောက်မရောက် Telegram မှာ စစ်ပါ",
    "Order #{no}": "အော်ဒါ #{no}", "Paid order #{no}": "ငွေချေပြီး အော်ဒါ #{no}",
    "Check the payment screenshot": "ငွေလွှဲ screenshot စစ်မယ်", "not in product list": "ပစ္စည်းစာရင်းထဲ မရှိ",
    "no price": "ဈေး မရှိ", "Not in the product list: {names}.": "ပစ္စည်းစာရင်းထဲ မရှိ: {names}။",
    "Payment info is blocked until you remove it (✕) or add the product with a price and add it again.":
        "ဒါကို ဖယ်မှ (✕) (သို့) ပစ္စည်းနဲ့ဈေး ထည့်ပြီး ပြန်ထည့်မှ ငွေလွှဲအချက်အလက် ပို့လို့ရမယ်။",
    "No price for {names}: add it in the price list, then": "{names} ဈေး မရှိ — ဈေးစာရင်းထဲ ထည့်ပြီးရင်",
    "refresh prices": "ဈေး ပြန်ယူမယ်",
    "No open cart. Add items with the one-tap buttons on buy messages, or below.":
        "ဖွင့်ထားတဲ့ ခြင်း မရှိ။ ဝယ်မယ့်စာတွေမှာ တစ်ချက်နှိပ်ခလုတ်နဲ့ (သို့) အောက်မှာ ထည့်ပါ။",
    "Add an item": "ပစ္စည်း ထည့်မယ်", "From their message": "သူ့စာထဲကနေ", "Move up": "အပေါ်တင်မယ်",
    "Last time": "လွန်ခဲ့တဲ့တစ်ခါ", "No phone yet.": "ဖုန်း မရှိသေး။", "Add phone": "ဖုန်း ထည့်မယ်",
    "Save address": "လိပ်စာ သိမ်းမယ်", "Payment info not possible yet": "ငွေလွှဲအချက်အလက် မပို့နိုင်သေး",
    "Mark confirmed": "အတည်ပြုပြီးလို့ မှတ်မယ်", "Cancel cart": "ခြင်း ပယ်မယ်",
    "What this customer is buying now. Follow the blue “Next” button: list → confirmed → phone → address → payment info.":
        "ဒီဖောက်သည် အခုဝယ်နေတာ။ အပြာရောင် “နောက်တစ်ဆင့်” ခလုတ်အတိုင်း လုပ်ပါ — စာရင်း → အတည်ပြု → ဖုန်း → လိပ်စာ → ငွေလွှဲအချက်အလက်။",
    "🛒 cart": "🛒 ခြင်း", "✅ confirmed": "✅ အတည်ပြုပြီး", "💳 waiting for payment": "💳 ငွေလွှဲဖို့ စောင့်နေ",
    "📷 payment photo received": "📷 ငွေလွှဲပုံ ရပြီ", "💳 waiting payment": "💳 ငွေစောင့်နေ",
    "📷 payment photo": "📷 ငွေလွှဲပုံ", "📦 to pack": "📦 ထုပ်ရန်", "🚚 to send": "🚚 ပို့ရန်", "sent out": "ပို့လိုက်ပြီ",
    "✅ delivered": "✅ ရောက်ပြီ", "abandoned": "ပစ်ထား",

    # ---------- payments ----------
    "Payments to check": "စစ်ရန် ငွေလွှဲများ", "Several photos ({n}) — ask for one": "ပုံ {n} ပုံ — တစ်ပုံပဲ ပို့ခိုင်းပါ",
    "Screenshot · total {total} ကျပ်": "Screenshot · စုစုပေါင်း {total} ကျပ်", "Nothing to check.": "စစ်စရာ မရှိပါ။",
    "Payment screenshots from customers. Open one, find the same transaction in your KPay / AYA app, type its ID and approve.":
        "ဖောက်သည်တွေ ပို့တဲ့ ငွေလွှဲ screenshot တွေ။ တစ်ခုဖွင့်ပါ၊ KPay / AYA app ထဲမှာ အဲဒီငွေလွှဲကို ရှာပါ၊ ID ရိုက်ပြီး အတည်ပြုပါ။",
    "Payment check": "ငွေလွှဲ စစ်ခြင်း", "order status": "အော်ဒါ အခြေအနေ", "Expected total": "ရရမယ့် စုစုပေါင်း",
    "Several photos ({n})": "ပုံ {n} ပုံ",
    "Not downloaded. Ask the customer for one screenshot with the transaction ID.":
        "မဖွင့်ထားပါ။ ငွေလွှဲ ID ပါတဲ့ screenshot တစ်ပုံပဲ ပို့ခိုင်းပါ။",
    "Ask for one screenshot": "Screenshot တစ်ပုံ ပို့ခိုင်းမယ်", "Not a payment": "ငွေလွှဲ မဟုတ်ဘူး",
    "Please check": "စစ်ကြည့်ပါ", "Transaction ID (from your KPay / AYA history)": "ငွေလွှဲ ID (KPay / AYA မှတ်တမ်းထဲက)",
    "Amount received (ကျပ်)": "ရတဲ့ ငွေ (ကျပ်)", "Method": "ငွေပေးနည်း", "Approve anyway": "ဒါပေမယ့် အတည်ပြုမယ်",
    "Gives the Order ID and sends the confirmation (10 s, Cancel in the chat).":
        "အော်ဒါနံပါတ် ပေးပြီး အတည်ပြုစာ ပို့မယ် (၁၀ စက္ကန့်၊ စကားပြောထဲမှာ ပယ်လို့ရ)။",
    "“Amount too low” uses the amount received above to ask for the rest.": "“ငွေနည်းနေ” ဆိုရင် အပေါ်က ရတဲ့ငွေနဲ့ ကျန်ငွေ တောင်းမယ်။",
    "Not a payment (nothing sent)": "ငွေလွှဲ မဟုတ်ဘူး (ဘာမှ မပို့ဘူး)", "Decided": "ဆုံးဖြတ်ပြီး", "transaction": "ငွေလွှဲ",
    "Open your KPay / AYA app, find this payment, copy its transaction ID and the amount here. Approve only if the money really arrived.":
        "KPay / AYA app ဖွင့်ပါ၊ ဒီငွေလွှဲကို ရှာပါ၊ ငွေလွှဲ ID နဲ့ ပမာဏကို ဒီမှာ ရိုက်ပါ။ ငွေ တကယ်ရောက်မှ အတည်ပြုပါ။",
    "Tap to zoom": "နှိပ်ပြီး ချဲ့ကြည့်", "Payment screenshot": "ငွေလွှဲ screenshot",
    "Could not load the screenshot": "Screenshot မဖွင့်နိုင်ပါ", "Loading the screenshot…": "Screenshot ဖွင့်နေတယ်…",
    "Money not received": "ငွေ မရောက်ပါ", "Wrong screenshot": "Screenshot မှားနေ",
    "Amount too low (ask for the rest)": "ငွေနည်းနေ (ကျန်ငွေ တောင်းမယ်)",

    # ---------- orders ----------
    "📦 To pack": "📦 ထုပ်ရန်", "🚚 To send": "🚚 ပို့ရန်", "Sent": "ပို့ပြီး", "✅ Delivered": "✅ ရောက်ပြီ", "All": "အားလုံး",
    "paid": "ငွေရပြီ", "Deli": "ပို့သူ", "Cancelled": "ပယ်ဖျက်ပြီး", "Undo {status}": "“{status}” ပြန်ဖျက်မယ်",
    "Packed": "ထုပ်ပြီး", "📦 Packed": "📦 ထုပ်ပြီး", "🚚 Sent out": "🚚 ပို့လိုက်ပြီ", "Sent out": "ပို့လိုက်ပြီ", "Deli name (optional)": "ပို့သူ နာမည် (မထည့်လည်းရ)",
    "Deli phone (optional)": "ပို့သူ ဖုန်း (မထည့်လည်းရ)", "Note for us (optional)": "ကိုယ့်အတွက် မှတ်ချက် (မထည့်လည်းရ)",
    "Sent out + tell the customer": "ပို့လိုက်ပြီ + ဖောက်သည်ကို ပြောမယ်", "Delivered": "ရောက်ပြီ",
    "The order is paid: refund the customer outside the system.": "ငွေချေပြီးသား အော်ဒါ — ငွေကို စနစ်ပြင်ပမှာ ပြန်အမ်းပါ။",
    "Note (refund, reason)": "မှတ်ချက် (ငွေပြန်အမ်း၊ အကြောင်းရင်း)",
    "Send “order cancelled” to the customer": "ဖောက်သည်ကို “အော်ဒါပယ်ပြီ” စာ ပို့မယ်", "No orders here.": "အော်ဒါ မရှိပါ။",
    "Sent-out orders become delivered by themselves after the days set in Settings.":
        "ပို့လိုက်တဲ့ အော်ဒါတွေ ဆက်တင်ထဲက ရက်ကျော်ရင် “ရောက်ပြီ” ဖြစ်သွားမယ်။",
    "Wanted but not stocked": "လိုချင်ကြပေမယ့် မရှိတာ",
    "Paid orders. Pack them, then press Sent out when the deli takes them, then Delivered.":
        "ငွေချေပြီး အော်ဒါတွေ။ ထုပ်ပါ၊ ပို့သူ ယူသွားရင် “ပို့လိုက်ပြီ” နှိပ်ပါ၊ ရောက်ရင် “ရောက်ပြီ” နှိပ်ပါ။",
    "customer cancelled": "ဖောက်သည်က ပယ်တယ်",

    # ---------- products, prices ----------
    "Search product or alias": "ပစ္စည်း (သို့) နာမည်ပွား ရှာမယ်", "Prices (ကျပ်)": "ဈေးများ (ကျပ်)", "Aliases": "နာမည်ပွားများ",
    "no prices": "ဈေး မရှိ", "out of stock": "ပစ္စည်းကုန်", "in stock": "ပစ္စည်းရှိ", "added here": "ဒီမှာ ထည့်ထား",
    "No products.": "ပစ္စည်း မရှိပါ။", "Add product": "ပစ္စည်း ထည့်မယ်", "Price list": "ဈေးစာရင်း",
    "The main list is the price list (Excel); a new row there also adds a product. Products added here are included in the Excel download.":
        "အဓိက စာရင်းက ဈေးစာရင်း (Excel) ပါ — အဲဒီမှာ စာကြောင်းအသစ်ထည့်ရင်လည်း ပစ္စည်းအသစ် ဖြစ်တယ်။ ဒီမှာ ထည့်တဲ့ပစ္စည်းတွေလည်း Excel ထဲ ပါမယ်။",
    "Every perfume we sell, with prices and the nicknames customers use for it.":
        "ရောင်းတဲ့ ရေမွှေးအားလုံး — ဈေးနှုန်းနဲ့ ဖောက်သည်တွေ ခေါ်တဲ့ နာမည်ပွားတွေ။",
"from CSV": "မူလစာရင်းက", "See messages for this product": "ဒီပစ္စည်းအကြောင်း စာတွေ ကြည့်မယ်",
    "Deactivate (stop matching it)": "မသုံးတော့ဘူး (မရှာတော့ဘူး)", "Activate": "ပြန်သုံးမယ်", "Stock": "လက်ကျန်",
    "Since": "စတဲ့ရက်", "No prices yet.": "ဈေး မရှိသေးပါ။", "Prices come from the price list (Excel).": "ဈေးတွေက ဈေးစာရင်း (Excel) ကလာတာ။",
    "Price history": "ဈေး မှတ်တမ်း", "not sold": "မရောင်း",
    "Words customers use for this product. The parser re-checks all messages within a few seconds after a change; your manual corrections are kept.":
        "ဖောက်သည်တွေ ဒီပစ္စည်းကို ခေါ်တဲ့ စာလုံးတွေ။ ပြင်ပြီး စက္ကန့်အနည်းငယ်အတွင်း စာအားလုံး ပြန်စစ်မယ် — ကိုယ်တိုင်ပြင်ထားတာတွေ မပျောက်ဘူး။",
    "Also an alias of another product, so the parser cannot decide": "တခြားပစ္စည်းရဲ့ နာမည်ပွားလည်း ဖြစ်နေလို့ App မဆုံးဖြတ်နိုင်ဘူး",
    "shared": "နှစ်ခုသုံး", "Delete alias": "နာမည်ပွား ဖျက်မယ်", "No aliases yet.": "နာမည်ပွား မရှိသေးပါ။",
    "New alias, e.g.": "နာမည်ပွားအသစ်၊ ဥပမာ", "New alias": "နာမည်ပွားအသစ်", "Add alias": "နာမည်ပွား ထည့်မယ်",
    "New nicknames: teach them with the 📘 card on a message (the owner approves).":
        "နာမည်အသစ်တွေကို စာတစ်စောင်ပေါ်က 📘 ကတ်နဲ့ သင်ပေးပါ (ပိုင်ရှင်က အတည်ပြုမယ်)။",
    "Download": "ဒေါင်းမယ်",
    "The current prices of every active product, in the same format as the upload. Edit it in Excel (or Google Sheets, then download as .xlsx).":
        "သုံးနေတဲ့ ပစ္စည်းအားလုံးရဲ့ လက်ရှိဈေး၊ တင်တဲ့ပုံစံအတိုင်း။ Excel (သို့) Google Sheets မှာ ပြင်ပြီး .xlsx အဖြစ် သိမ်းပါ။",
    "Download current prices (.xlsx)": "လက်ရှိဈေး ဒေါင်းမယ် (.xlsx)", "Upload": "တင်မယ်",
    "Price list (.xlsx, max 2 MB)": "ဈေးစာရင်း (.xlsx၊ အများဆုံး 2 MB)", "Check file": "ဖိုင် စစ်မယ်",
    "You see a preview first. Nothing is saved until you press Confirm.": "အရင် ကြိုကြည့်ရမယ်။ အတည်ပြု မနှိပ်မချင်း ဘာမှ မသိမ်းဘူး။",
    "File format": "ဖိုင် ပုံစံ", "Any header like 3ml or 15ml adds that decant size.": "3ml (သို့) 15ml လို ခေါင်းစဉ်ထည့်ရင် အဲဒီဆိုဒ် ရောင်းမယ်။",
    "Empty price cell = that size is not sold. A size column missing from the file leaves that size unchanged.":
        "ဈေးကွက်လပ် = အဲဒီဆိုဒ် မရောင်း။ ဖိုင်ထဲ မပါတဲ့ ဆိုဒ်ကော်လံ = မပြောင်းဘူး။",
    "for the whole perfume; empty = unchanged.": "ရေမွှေးတစ်ခုလုံးအတွက် (ရှိ / မရှိ) — လပ်ထား = မပြောင်းဘူး။",
    "A new brand + name adds a product. Names close to an existing product are shown for you to decide.":
        "အမှတ်တံဆိပ် + နာမည် အသစ်ဆို ပစ္စည်းအသစ် ဖြစ်မယ်။ ရှိပြီးသားနဲ့ ဆင်တဲ့နာမည်တွေကို ဆုံးဖြတ်ဖို့ ပြမယ်။",
    "Last upload": "နောက်ဆုံး တင်ခဲ့တာ", "{n} price changes": "ဈေးပြောင်း {n} ခု", "Check prices": "ဈေး စစ်မယ်",
    "Check before saving": "မသိမ်းခင် စစ်ပါ", "{n} perfumes. Nothing is saved yet.": "ရေမွှေး {n} မျိုး။ ဘာမှ မသိမ်းရသေးပါ။",
    "Fix these in the file, then upload again": "ဖိုင်ထဲမှာ ဒါတွေပြင်ပြီး ပြန်တင်ပါ", "{n} changed": "ပြောင်း {n}",
    "{n} new": "အသစ် {n}", "{n} to decide": "ဆုံးဖြတ်ရန် {n}", "{n} no change": "မပြောင်း {n}",
    "Not sure which product": "ဘယ်ပစ္စည်းလဲ မသေချာ", "row {n}": "စာကြောင်း {n}", "This is": "ဒါက", "choose": "ရွေးပါ",
    "update it": "ပြင်မယ်", "a new product": "ပစ္စည်းအသစ်", "skip this row": "ဒီစာကြောင်း ကျော်မယ်", "New products": "ပစ္စည်းအသစ်များ",
    "Add as new product": "ပစ္စည်းအသစ်အဖြစ် ထည့်မယ်", "Skip this row": "ဒီစာကြောင်း ကျော်မယ်", "Changes": "ပြောင်းတာများ",
    "product is inactive → will be activated": "မသုံးတော့တဲ့ပစ္စည်း → ပြန်သုံးမယ်",
    "{n} products not in this file (left as they are)": "ဒီဖိုင်ထဲ မပါတဲ့ ပစ္စည်း {n} ခု (မပြောင်းဘူး)",
    "Confirm and save": "အတည်ပြုပြီး သိမ်းမယ်",
    "Can't save: fix the problems above in the file and upload it again.": "မသိမ်းနိုင်ပါ — အပေါ်က ပြဿနာတွေ ဖိုင်ထဲမှာပြင်ပြီး ပြန်တင်ပါ။",
    "Full {n}ml": "ပုလင်းလိုက် {n}ml",

    # ---------- sales, wanted, health ----------
    "Sales & profit": "အရောင်းနဲ့ အမြတ်", "Date range": "ရက်", "From": "မှ", "To": "အထိ", "Export .xlsx": ".xlsx ထုတ်မယ်",
    "paid orders only (paid, packed, sent out, delivered), by the day they were paid (Yangon time).":
        "ငွေချေပြီး အော်ဒါတွေပဲ (ငွေရ၊ ထုပ်၊ ပို့၊ ရောက်)၊ ငွေချေတဲ့ရက်အလိုက် (ရန်ကုန်အချိန်)။",
    "Revenue": "ရောင်းရငွေ", "Items sold": "ရောင်းရတဲ့ အရေအတွက်", "ml sold": "ရောင်းရတဲ့ ml", "Cost": "ကုန်ကျစရိတ်",
    "Profit": "အမြတ်", "Profit %": "အမြတ် %", "Average order": "အော်ဒါ ပျမ်းမျှ",
    "Profit {missing}: some items have no cost — add bottle_cost in the price list (and the vial cost per size in Settings).":
        "အမြတ် {missing}: တချို့ပစ္စည်းတွေ ကုန်ကျစရိတ် မရှိ — ဈေးစာရင်းထဲ bottle_cost ထည့်ပါ (ဆက်တင်ထဲမှာ ပုလင်းသေး ကုန်ကျစရိတ်လည်း)။",
    "Use today's costs for {n} order(s) already paid": "ငွေချေပြီး အော်ဒါ {n} ခုအတွက် ဒီနေ့ ကုန်ကျစရိတ် သုံးမယ်",
    "Revenue per day": "တစ်ရက်ချင်း ရောင်းရငွေ", "{day}: {revenue} ကျပ် · {n} order(s)": "{day}: {revenue} ကျပ် · အော်ဒါ {n} ခု", "highest": "အများဆုံး", "No paid orders.": "ငွေချေပြီး အော်ဒါ မရှိပါ။",
    "Per day": "တစ်ရက်ချင်း", "Day": "ရက်", "Per perfume (by revenue)": "ရေမွှေးအလိုက် (ရောင်းရငွေ အများဆုံးအရင်)",
    "Perfume": "ရေမွှေး", "Per size": "ဆိုဒ်အလိုက်", "Money from paid orders. Choose a day range at the top.":
        "ငွေချေပြီး အော်ဒါတွေက ရတဲ့ငွေ။ အပေါ်မှာ ရက်ရွေးပါ။",
    "Wanted": "လိုချင်ကြတာ",
    "Products customers asked for that you marked “We don't have it”, and sizes that are out of stock now (from the price list). Most asked first.":
        "“ဒီပစ္စည်း မရှိဘူး” လို့ မှတ်ထားတဲ့ ဖောက်သည်မေးတဲ့ ပစ္စည်းတွေနဲ့ အခုကုန်နေတဲ့ ဆိုဒ်တွေ (ဈေးစာရင်းက)။ အမေးများဆုံး အပေါ်မှာ။",
    "Times asked": "မေးတဲ့ အကြိမ်", "Last asked": "နောက်ဆုံး မေးတာ", "not in list": "စာရင်းထဲ မရှိ",
    "Perfumes customers asked for that we don't sell or that are out of stock. Tell the owner about the top ones.":
        "ဖောက်သည်တွေ မေးပေမယ့် မရောင်းတာ (သို့) ကုန်နေတဲ့ ရေမွှေးတွေ။ အပေါ်ဆုံးကဟာတွေကို ပိုင်ရှင်ကို ပြောပါ။",
    "Something needs attention": "တစ်ခုခု စစ်ဖို့ လိုတယ်", "All systems OK": "အားလုံး ကောင်းပါတယ်",
    "Last message received": "နောက်ဆုံး ရတဲ့စာ", "{n} messages stored.": "စာ {n} စောင် သိမ်းထားတယ်။",
    "Services restart on their own. If one stays red, tell the owner. On the server run:":
        "ပြဿနာတက်ရင် အလိုလို ပြန်စတယ်။ အနီရောင် ဆက်ဖြစ်နေရင် ပိုင်ရှင်ကို ပြောပါ။ Server ပေါ်မှာ ဒါ run ပါ:",
    "database": "ဒေတာဘေ့စ်", "listener": "စာလက်ခံ", "parser": "စာဖတ်", "parse queue": "ဖတ်ရန် စာ", "backup": "အရန်သိမ်း",
    "disk": "ဒစ်", "connected": "ချိတ်ထား", "cannot connect": "မချိတ်နိုင်", "never reported": "သတင်း မပို့ဖူး",
    "empty": "မရှိ", "no backup yet": "အရန် မသိမ်းရသေး", "none yet": "မရှိသေး",
    "last heartbeat {ago} ({info})": "နောက်ဆုံး သတင်းပို့ {ago} ({info})", "{n}s ago": "{n} စက္ကန့်က",
    "{n} min ago": "{n} မိနစ်က", "{n} h ago": "{n} နာရီက", "{n} days ago": "{n} ရက်က",
    "{n} waiting, oldest {ago}": "{n} စောင် စောင့်နေ၊ အဟောင်းဆုံး {ago}",
    "{name}, {ago}, {size} KiB, {n} kept": "{name}၊ {ago}၊ {size} KiB၊ {n} ခု သိမ်းထား", "{n} GiB free ({pct})": "{n} GiB လွတ် ({pct})",

    # ---------- learning ----------
    "What the team taught with teaching cards. Waiting ones are only suggested (one tap, never automatic) until you approve them.":
        "သင်ပေးကတ်နဲ့ အဖွဲ့က သင်ပေးထားတာတွေ။ စောင့်နေတာတွေကို မအတည်ပြုမချင်း အကြံပြုရုံပဲ (တစ်ချက်နှိပ်၊ အလိုအလျောက် မဟုတ်)။",
    "Or they are approved by themselves after {n} accepts without a correction.": "(သို့) မပြင်ဘဲ {n} ကြိမ် လက်ခံရင် အလိုလို အတည်ဖြစ်မယ်။",
    "Waiting for approval": "အတည်ပြုဖို့ စောင့်နေ", "Approved": "အတည်ပြုပြီး",
    "Handled by learned patterns this week": "ဒီအပတ် သင်ထားတာနဲ့ ဖြေပြီး", "Needs your decision": "ဆုံးဖြတ်ဖို့ လိုတယ်",
    "“{text}” was taught as": "“{text}” ကို ဒီလို သင်ထားတယ်:", "a product": "ပစ္စည်းတစ်ခု", "we don't sell it": "မရောင်းဘူး",
    "but it is already {what}.": "ဒါပေမယ့် {what} ဖြစ်နေပြီ။", "Use the new answer": "အဖြေအသစ် သုံးမယ်",
    "Keep it as it is": "ဒီအတိုင်း ထားမယ်", "Nothing waiting.": "စောင့်နေတာ မရှိပါ။", "taught by": "သင်ပေးသူ",
    "used {n}×": "{n} ကြိမ် သုံး", "corrected {n}×": "{n} ကြိမ် ပြင်", "auto-approved after {n} uses": "{n} ကြိမ် သုံးပြီး အလိုလို အတည်",
    "Learning settings": "သင်ယူမှု ဆက်တင်",
    "Approve by itself after this many one-tap accepts without a correction (0 = only you approve)":
        "မပြင်ဘဲ ဒီအကြိမ်ရေ လက်ခံရင် အလိုလို အတည်ပြုမယ် (0 = ကိုယ်တိုင်ပဲ အတည်ပြု)",
    "Answer a message that is only a greeting (“hi”) with the greeting reply": "နှုတ်ဆက်ရုံ စာ (“hi”) ကို နှုတ်ဆက်စာနဲ့ ပြန်ဖြေမယ်",
    "Auto-reply “we don't have it” for approved “we don't sell” names": "အတည်ပြုထားတဲ့ “မရောင်းဘူး” နာမည်တွေကို “မရှိဘူး” လို့ အလိုအလျောက် ဖြေမယ်",
    "📛 Nicknames (ပစ္စည်းနာမည်)": "📛 ပစ္စည်းနာမည်", "💬 Phrases (လုပ်ချင်တာ)": "💬 လုပ်ချင်တာ",
    "🚫 We don't sell (မရှိဘူး)": "🚫 မရောင်းဘူး (မရှိဘူး)",
    "an alias of {name}": "{name} ရဲ့ နာမည်ပွား", "a nickname of {name}": "{name} ရဲ့ နာမည်ပွား",
    "a learned nickname of {name}": "{name} ရဲ့ သင်ထားတဲ့ နာမည်", "marked “we don't sell it”": "“မရောင်းဘူး” လို့ မှတ်ထား",
    "taught as “{what}”": "“{what}” လို့ သင်ထား", "learned pattern waiting for approval": "အတည်ပြုဖို့ စောင့်နေတဲ့ သင်ထားချက်",

    # ---------- settings ----------
    "Auto-reply speed": "အလိုအလျောက်ဖြေ မြန်နှုန်း",
    "Time from the customer's message to an automatic reply ≈ quiet + delay. Shorter = faster, but looks more like a bot.":
        "ဖောက်သည်စာကနေ အလိုအလျောက်ဖြေစာအထိ အချိန် ≈ စောင့်ချိန် + နှောင့်နှေးချိန်။ တိုရင် မြန်တယ်၊ ဒါပေမယ့် စက်ရုပ်နဲ့ ပိုတူတယ်။",
    "Wait for the customer to stop typing (s)": "ဖောက်သည် စာရိုက်ပြီးတာ စောင့် (စက္ကန့်)", "Shortest delay (s)": "အတိုဆုံး စောင့်ချိန် (စက္ကန့်)",
    "Longest delay (s)": "အရှည်ဆုံး စောင့်ချိန် (စက္ကန့်)", "Save speed": "မြန်နှုန်း သိမ်းမယ်", "Orders & payments": "အော်ဒါနဲ့ ငွေလွှဲ",
    "Reminder and cancel are sent only while auto-reply is ON; otherwise the order waits in “Needs you” with a button.":
        "အလိုအလျောက်ဖြေ ဖွင့်ထားမှ သတိပေးစာနဲ့ ပယ်စာ ပို့မယ် — မဟုတ်ရင် “ကိုယ်တိုင်လုပ်ရန်” ထဲမှာ ခလုတ်နဲ့ စောင့်မယ်။",
    "Payment reminder after (hours)": "ငွေလွှဲ သတိပေးချိန် (နာရီ)", "Cancel unpaid order after (hours)": "ငွေမလွှဲရင် ပယ်မယ့်အချိန် (နာရီ)",
    "Sent out → delivered after (days)": "ပို့လိုက်ပြီ → ရောက်ပြီ (ရက်)", "Send thank-you on delivered": "ရောက်ရင် ကျေးဇူးတင်စာ ပို့မယ်",
    "Vial cost per decant size": "ဆိုဒ်အလိုက် ပုလင်းသေး ကုန်ကျစရိတ်",
    "Cost of the empty vial / packaging, added to the perfume cost of each decant (Sales page). Bottle costs come from the price list (bottle_cost column). Saved on each order when it is paid.":
        "ပုလင်းသေးအလွတ် / ထုပ်ပိုးခ — ခွဲရောင်းတိုင်း ရေမွှေးကုန်ကျစရိတ်ထဲ ပေါင်းမယ် (အရောင်း စာမျက်နှာ)။ ပုလင်းကြီးဈေးက ဈေးစာရင်း (bottle_cost) ကလာတာ။ ငွေချေတဲ့အချိန် အော်ဒါမှာ သိမ်းမယ်။",
    "{size}ml vial (ကျပ်)": "{size}ml ပုလင်းသေး (ကျပ်)", "Save vial costs": "ပုလင်းသေး ကုန်ကျစရိတ် သိမ်းမယ်", "FAQ answers": "FAQ အဖြေများ",
    "Common questions. A message that names no product and matches keywords gets the answer (automatically when auto-reply is ON, otherwise a one-tap “💬 Send FAQ” button). Keywords: comma separated, Burmese or English. Most keywords found wins.":
        "မေးလေ့ရှိတဲ့ မေးခွန်းတွေ။ ပစ္စည်းမပါဘဲ သော့ချက်စာလုံး ကိုက်တဲ့စာကို ဒီအဖြေ ပေးမယ် (အလိုအလျောက်ဖြေ ဖွင့်ထားရင် အလိုလို၊ မဟုတ်ရင် “💬 FAQ အဖြေ ပို့မယ်” ခလုတ်)။ သော့ချက်စာလုံး: ကော်မာခြား၊ မြန်မာ (သို့) အင်္ဂလိပ်။ အများဆုံး ကိုက်တာ ရွေးမယ်။",
    "Title": "ခေါင်းစဉ်", "edit me": "ပြင်ပါ", "Keywords": "သော့ချက်စာလုံး", "Answer": "အဖြေ", "Add FAQ": "FAQ ထည့်မယ်",
    "Payment methods": "ငွေပေးနည်းများ", "Active methods are listed in the payment info message to customers.":
        "သုံးနေတဲ့ ငွေပေးနည်းတွေကို ဖောက်သည်ဆီ ငွေလွှဲအချက်အလက်စာထဲ ထည့်မယ်။",
    "Account number": "အကောင့် နံပါတ်", "Account name": "အကောင့် နာမည်",
    "No payment methods yet. Add at least one before sending payment info.": "ငွေပေးနည်း မရှိသေးပါ။ ငွေလွှဲအချက်အလက် မပို့ခင် အနည်းဆုံး တစ်ခု ထည့်ပါ။",
    "Add payment method": "ငွေပေးနည်း ထည့်မယ်", "Reply templates": "အသင့်ဖြေစာများ",
    "Texts the dashboard suggests when you reply to a customer. You can still edit each message before it is sent. Words in {braces} are filled in automatically.":
        "ဖောက်သည်ကို ဖြေတဲ့အခါ Dashboard က အကြံပြုတဲ့ စာတွေ။ မပို့ခင် ပြင်လို့ရတယ်။ {ကွင်း} ထဲက စာလုံးတွေကို အလိုလို ဖြည့်မယ်။",
    "Placeholders": "အလိုလိုဖြည့်မယ့်နေရာ", "No placeholders.": "အလိုလိုဖြည့်တာ မရှိ။", "reset to default": "မူလစာ ပြန်ထားမယ်",

    # ---------- users, activity ----------
    "Staff can do the daily work: inbox, Needs you, chats, replies, teaching cards, carts, order statuses, reports (read only).":
        "ဝန်ထမ်းတွေ နေ့စဉ်အလုပ် လုပ်နိုင်တယ် — စာဝင်၊ ကိုယ်တိုင်လုပ်ရန်၊ စကားပြော၊ ဖြေစာ၊ သင်ပေးကတ်၊ ခြင်း၊ အော်ဒါအခြေအနေ၊ စာရင်းချုပ် (ကြည့်ရုံ)။",
    "Staff may also check payments.": "ဝန်ထမ်းတွေ ငွေလွှဲလည်း စစ်နိုင်တယ်။",
    "Only you change prices, products, payment methods, templates, FAQ, settings, auto-reply, users, and approve what the app learned. Staff see sales revenue, not cost or profit.":
        "ဈေး၊ ပစ္စည်း၊ ငွေပေးနည်း၊ အသင့်စာ၊ FAQ၊ ဆက်တင်၊ အလိုအလျောက်ဖြေ၊ အသုံးပြုသူ ပြောင်းတာနဲ့ App သင်ထားတာ အတည်ပြုတာ ကိုယ်တိုင်ပဲ လုပ်နိုင်တယ်။ ဝန်ထမ်းတွေ ရောင်းရငွေပဲ မြင်ရတယ်၊ ကုန်ကျစရိတ်နဲ့ အမြတ် မမြင်ရဘူး။",
    "User": "အသုံးပြုသူ", "Role": "ရာထူး", "disabled": "ပိတ်ထား", "Reset password": "စကားဝှက် အသစ်ပေးမယ်",
    "New password": "စကားဝှက် အသစ်", "Set": "သတ်မှတ်မယ်", "Enable": "ပြန်ဖွင့်မယ်", "Disable": "ပိတ်မယ်",
    "Add a user": "အသုံးပြုသူ ထည့်မယ်", "Password (min {n})": "စကားဝှက် (အနည်းဆုံး {n} လုံး)", "Add user": "အသုံးပြုသူ ထည့်မယ်",
    "Or on the server": "(သို့) Server ပေါ်မှာ", "What staff may do": "ဝန်ထမ်း လုပ်ခွင့်",
    "Staff may approve / reject payment screenshots": "ဝန်ထမ်းတွေ ငွေလွှဲ screenshot အတည်ပြု / ငြင်း လုပ်ခွင့်ရှိ",
    "Activity: who did what": "လုပ်ဆောင်ချက်: ဘယ်သူ ဘာလုပ်ခဲ့လဲ", "Activity": "လုပ်ဆောင်ချက်", "Everyone": "အားလုံး",
    "Automatic": "အလိုအလျောက်", "{n} today": "ဒီနေ့ {n} ခု",

    # ---------- login, errors ----------
    "Wrong username or password.": "အသုံးပြုသူအမည် (သို့) စကားဝှက် မှားနေတယ်။",
    "Too many failed attempts. Wait 15 minutes.": "အကြိမ်များလွန်းလို့ ၁၅ မိနစ် စောင့်ပါ။",
    "Can't do that": "မလုပ်နိုင်ပါ", "Not allowed": "ခွင့်မပြုပါ", "Not found": "မတွေ့ပါ", "Not Found": "မတွေ့ပါ",
    "Already changed": "ပြောင်းပြီးသား", "Something went wrong": "တစ်ခုခု မှားသွားတယ်",
    "Only the owner can do this.": "ဒါကို ပိုင်ရှင်ပဲ လုပ်နိုင်တယ်။",
    "Form expired. Go back, reload the page and try again.": "Form သက်တမ်းကုန်ပြီ။ နောက်ပြန်သွားပြီး စာမျက်နှာ ပြန်ဖွင့်ကာ ထပ်ကြိုးစားပါ။",
    "Only the owner checks payments now (Users > staff settings).": "အခု ငွေလွှဲကို ပိုင်ရှင်ပဲ စစ်တယ်။",
    "Customer not found": "ဖောက်သည် မတွေ့ပါ", "Message not found": "စာ မတွေ့ပါ", "Order not found": "အော်ဒါ မတွေ့ပါ",
    "Product not found": "ပစ္စည်း မတွေ့ပါ", "User not found": "အသုံးပြုသူ မတွေ့ပါ", "Payment check not found": "ငွေလွှဲစစ်ချက် မတွေ့ပါ",
    "Photo not found": "ဓာတ်ပုံ မတွေ့ပါ", "Photo not downloaded": "ဓာတ်ပုံ မဖွင့်ရသေး", "Photo file missing": "ဓာတ်ပုံဖိုင် မရှိ",
    "Not in the cart": "ခြင်းထဲ မရှိ", "No open cart": "ဖွင့်ထားတဲ့ ခြင်း မရှိ", "Already resolved": "ဖြေရှင်းပြီးသား",
    "Not waiting for payment": "ငွေ မစောင့်နေပါ", "Nothing to confirm": "အတည်ပြုစရာ မရှိ", "Nothing to clear": "ရှင်းစရာ မရှိ",
    "Choose a product": "ပစ္စည်း ရွေးပါ", "Choose a product and a size": "ပစ္စည်းနဲ့ ဆိုဒ် ရွေးပါ",
    "Choose at least one product.": "ပစ္စည်း အနည်းဆုံး တစ်ခု ရွေးပါ။", "Already sent or being sent": "ပို့ပြီး (သို့) ပို့နေပြီ",
    "Only failed messages can be retried": "မပို့နိုင်တဲ့စာကိုပဲ ထပ်ပို့လို့ရတယ်", "No such phone": "ဒီဖုန်း မရှိ",
    "Nothing saved from last time": "အရင်တစ်ခါက သိမ်းထားတာ မရှိ", "Unknown language": "မသိတဲ့ ဘာသာစကား",
    "This customer has never messaged us; we never message first.": "ဒီလူက စာမပို့ဖူးလို့ ကိုယ်က အရင် စာမပို့ပါ။",

    # ---------- flash notes and labels built in Python ----------
    "Saved.": "သိမ်းပြီး။", "Done.": "ပြီးပြီ။", "Cancelled.": "ပယ်ဖျက်ပြီး။", "Removed.": "ဖယ်ပြီး။", "Undone.": "ပြန်ဖျက်ပြီး။",
    "Done. The reply goes out in {n} s unless you undo.": "ပြီးပြီ။ ပြန်မဖျက်ရင် {n} စက္ကန့်အတွင်း စာပို့မယ်။",
    "The reply goes out in {n} s unless you undo.": "ပြန်မဖျက်ရင် {n} စက္ကန့်အတွင်း စာပို့မယ်။",
    "Done: nothing sent.": "ပြီးပြီ — ဘာမှ မပို့ဘူး။",
    "Saved. The owner adds the price, then the list goes out by itself.": "သိမ်းပြီး။ ပိုင်ရှင် ဈေးထည့်ရင် စာရင်း အလိုလို ပို့မယ်။",
    "Saved. Nothing to send automatically: reply in the chat.": "သိမ်းပြီး။ အလိုလို ပို့စရာ မရှိ — စကားပြောထဲမှာ ကိုယ်တိုင် ဖြေပါ။",
    "The reply changed meanwhile (price, cart). Check it again.": "ဖြေစာ ပြောင်းသွားပြီ (ဈေး၊ ခြင်း)။ ပြန်စစ်ပါ။",
    "Not possible any more (already handled, or a reply is waiting to go out).": "မလုပ်နိုင်တော့ပါ (ဖြေပြီးသား၊ (သို့) စာတစ်စောင် ပို့ဖို့ စောင့်နေ)။",
    "Not sent: the reply changed (price, cart or parse). Check and try again.": "မပို့ရ — ဖြေစာ ပြောင်းသွားပြီ (ဈေး၊ ခြင်း)။ စစ်ပြီး ထပ်ကြိုးစားပါ။",
    "Marked {status}.": "“{status}” လို့ မှတ်ပြီး။", "Queued. It is sent within a few seconds.": "တန်းစီပြီ။ စက္ကန့်အနည်းငယ်အတွင်း ပို့မယ်။",
    "Queued again.": "ထပ်တန်းစီပြီ။", "Too late: it is being sent.": "နောက်ကျသွားပြီ — ပို့နေပြီ။",
    "Already queued (sent twice by mistake?).": "တန်းစီပြီးသား (နှစ်ခါ နှိပ်မိလား?)။", "Added.": "ထည့်ပြီး။",
    "No price yet for {names}.": "{names} ဈေး မရှိသေး။", "Marked confirmed.": "အတည်ပြုပြီးလို့ မှတ်ပြီး။",
    "Address saved (also for next time).": "လိပ်စာ သိမ်းပြီး (နောက်တစ်ခါအတွက်ပါ)။", "Phone added.": "ဖုန်း ထည့်ပြီး။",
    "Not a Myanmar mobile number (09…).": "မြန်မာ ဖုန်းနံပါတ် မဟုတ်ပါ (09…)။",
    "Already saved, or {n} numbers already: remove one first.": "သိမ်းပြီးသား (သို့) {n} လုံး ပြည့်နေပြီ — တစ်လုံး အရင်ဖယ်ပါ။",
    "Using the same phone & address as last time.": "အရင်တစ်ခါက ဖုန်းနဲ့ လိပ်စာ သုံးမယ်။", "Cart cancelled.": "ခြင်း ပယ်ပြီး။",
    "{n} price(s) filled in.": "ဈေး {n} ခု ဖြည့်ပြီး။", "No new prices found.": "ဈေးအသစ် မတွေ့ပါ။",
    "Not sent: the message must be 1-{n} characters.": "မပို့ရ — စာက ၁ လုံးကနေ {n} လုံးအထိ ဖြစ်ရမယ်။",
    "Customer ignored: their messages are hidden from the inbox.": "ဖောက်သည်ကို လျစ်လျူရှုပြီ — သူ့စာတွေ စာဝင်မှာ မပြတော့ဘူး။",
    "Customer no longer ignored.": "ဖောက်သည်ကို လျစ်လျူ မရှုတော့ဘူး။",
    "Approved: Order #{no}. The confirmation goes out in a few seconds (Cancel in the chat).":
        "အတည်ပြုပြီး: အော်ဒါ #{no}။ အတည်ပြုစာ စက္ကန့်အနည်းငယ်အတွင်း ပို့မယ် (စကားပြောထဲမှာ ပယ်လို့ရ)။",
    "Rejected: the customer is told why; the order waits for payment again.": "ငြင်းပြီး — ဖောက်သည်ကို အကြောင်းပြောမယ်၊ အော်ဒါ ငွေလွှဲဖို့ ပြန်စောင့်မယ်။",
    "Dismissed: not a payment (nothing sent).": "ဖျောက်ပြီး — ငွေလွှဲ မဟုတ်ဘူး (ဘာမှ မပို့ဘူး)။",
    "Asked for one screenshot.": "Screenshot တစ်ပုံ ပို့ခိုင်းပြီး။",
    "Order #{no}: {done}.": "အော်ဒါ #{no}: {done}။",
    "The customer gets the message in 60 s (Undo to stop it).": "ဖောက်သည်ဆီ ၆၀ စက္ကန့်အတွင်း စာရောက်မယ် (ပြန်ဖျက်ရင် မပို့ဘူး)။",
    "Undo for 60 s.": "၆၀ စက္ကန့်အတွင်း ပြန်ဖျက်လို့ရ။", "Undone: order is {status} again.": "ပြန်ဖျက်ပြီး — အော်ဒါ “{status}” ပြန်ဖြစ်ပြီ။",
    "Payment reminder queued (60 s; Cancel in the chat).": "ငွေလွှဲ သတိပေးစာ တန်းစီပြီ (၆၀ စက္ကန့်၊ စကားပြောထဲမှာ ပယ်လို့ရ)။",
    "Price saved for {name}.": "{name} ဈေး သိမ်းပြီး။", "The list goes out in {n} s (Undo in the inbox).": "စာရင်း {n} စက္ကန့်အတွင်း ပို့မယ် (စာဝင်ထဲမှာ ပြန်ဖျက်လို့ရ)။",
    "Type the price in ကျပ်.": "ဈေးကို ကျပ်နဲ့ ရိုက်ပါ။", "Learning settings saved.": "သင်ယူမှု ဆက်တင် သိမ်းပြီး။",
    "“{text}”: approved — used automatically from now on.": "“{text}”: အတည်ပြုပြီး — အခုကစပြီး အလိုလို သုံးမယ်။",
    "“{text}”: removed.": "“{text}”: ဖယ်ပြီး။", "Staff settings saved.": "ဝန်ထမ်း ဆက်တင် သိမ်းပြီး။",
    "You can't disable yourself.": "ကိုယ့်ကိုယ်ကို ပိတ်လို့ မရပါ။", "Auto-reply resumed for this chat.": "ဒီစကားပြောအတွက် အလိုအလျောက်ဖြေ ပြန်ဖွင့်ပြီ။",
    "Never auto-reply to this customer.": "ဒီလူကို ဘယ်တော့မှ အလိုအလျောက် မဖြေတော့ဘူး။",
    "Auto-reply allowed for this customer again.": "ဒီလူကို အလိုအလျောက်ဖြေတာ ပြန်ခွင့်ပြုပြီ။",
    "Auto-reply is OFF: one-tap buttons only.": "အလိုအလျောက်ဖြေ ပိတ်ပြီ — တစ်ချက်နှိပ် ခလုတ်တွေပဲ။",
    "Auto-reply is ON: certain messages from now on are answered by themselves (8-20 s, Cancel in the chat).":
        "အလိုအလျောက်ဖြေ ဖွင့်ပြီ — သေချာတဲ့စာတွေကို အခုကစပြီး အလိုလို ဖြေမယ် (၈-၂၀ စက္ကန့်၊ စကားပြောထဲမှာ ပယ်လို့ရ)။",
    "FAQ “{title}” goes out in {n} s (Cancel in the chat).": "FAQ “{title}” {n} စက္ကန့်အတွင်း ပို့မယ် (စကားပြောထဲမှာ ပယ်လို့ရ)။",
    "Customer agreed: mark confirmed": "ဖောက်သည် သဘောတူပြီ: အတည်ပြုပြီးလို့ မှတ်မယ်", "Send cart list": "ခြင်းစာရင်း ပို့မယ်",
    "Same phone & address as last time": "အရင်တစ်ခါက ဖုန်းနဲ့ လိပ်စာ", "Ask for phone": "ဖုန်း မေးမယ်", "Ask for address": "လိပ်စာ မေးမယ်",
    "Send payment info": "ငွေလွှဲအချက်အလက် ပို့မယ်", "Waiting for the payment screenshot": "ငွေလွှဲ screenshot စောင့်နေ",
    "The cart is empty.": "ခြင်း ဗလာ။", "The customer has not confirmed the cart yet.": "ဖောက်သည်က ခြင်းကို မအတည်ပြုရသေး။",
    "No price for: {names}.": "ဈေး မရှိ: {names}။", "No phone yet.": "ဖုန်း မရှိသေး။", "No address yet.": "လိပ်စာ မရှိသေး။",
    "No active payment method (Settings).": "ငွေပေးနည်း မရှိ (ဆက်တင်)။",
    "{name}: no prices yet. Add them in the price list (Excel).": "{name}: ဈေး မရှိသေး။ ဈေးစာရင်း (Excel) ထဲ ထည့်ပါ။",
    "{name} is out of stock: the out-of-stock reply is used.": "{name} ကုန်နေ — “ကုန်နေ” စာ သုံးမယ်။",
    "{name} {size} has no price. Sizes sold: {have}.": "{name} {size} ဈေး မရှိ။ ရောင်းတဲ့ဆိုဒ်: {have}။",
    "{name} {size} is out of stock: the out-of-stock reply is used.": "{name} {size} ကုန်နေ — “ကုန်နေ” စာ သုံးမယ်။",
    "auto-reply is off": "အလိုအလျောက်ဖြေ ပိတ်ထား", "ignored customer": "လျစ်လျူရှုထားတဲ့ ဖောက်သည်",
    "never auto-reply to this customer": "ဒီလူကို အလိုအလျောက် မဖြေနဲ့", "paused: owner is replying by hand": "ခဏရပ်ထား — ကိုယ်တိုင် ဖြေနေတယ်",
    "auto not paid in {n} h": "{n} နာရီ ငွေမလွှဲလို့ အလိုလို ပယ်",

    # one-tap button labels and notes (app/orders/actions.py)
    "💬 Reply price": "💬 ဈေး ပြန်ပြောမယ်", "💬 Reply: we don't have it": "💬 “မရှိဘူး” လို့ ပြန်ပြောမယ်",
    "💬 Reply delivery status": "💬 ပို့ဆောင်မှု အခြေအနေ ပြန်ပြောမယ်", "🚫 Cancel order + reply": "🚫 အော်ဒါ ပယ်ပြီး ပြန်ပြောမယ်",
    "➖ Remove + send list": "➖ ဖယ်ပြီး စာရင်းပို့မယ်", "💬 Send cart list": "💬 ခြင်းစာရင်း ပို့မယ်", "✅ Confirm": "✅ အတည်ပြုမယ်",
    "👋 Reply greeting": "👋 နှုတ်ဆက်စာ ပြန်ပို့မယ်", "🛒 Add to cart + send list": "🛒 ခြင်းထဲထည့်ပြီး စာရင်းပို့မယ်",
    "🛒 Add the earlier item + send list": "🛒 အရင်ကဟာ ထည့်ပြီး စာရင်းပို့မယ်", "🔢 Ask which earlier item": "🔢 အရင်ကဟာ ဘယ်ဟာလဲ မေးမယ်",
    "🛒 Add {n} known item + send list": "🛒 သိတဲ့ပစ္စည်း {n} ခု ထည့်ပြီး စာရင်းပို့မယ်",
    "🛒 Add {n} known items + send list": "🛒 သိတဲ့ပစ္စည်း {n} ခု ထည့်ပြီး စာရင်းပို့မယ်",
    "💬 Send FAQ: {title}": "💬 FAQ ပို့မယ်: {title}", "📘 {label}": "📘 {label}", "✅ Confirm{rest}": "✅ အတည်ပြုမယ်{rest}",
    " + ask phone": " + ဖုန်းမေး", " + ask address": " + လိပ်စာမေး", " + 💳 send payment info": " + 💳 ငွေလွှဲအချက်အလက် ပို့",
    "Cart confirmed.": "ခြင်း အတည်ပြုပြီး။", "Cart total {total} ကျပ်.": "ခြင်း စုစုပေါင်း {total} ကျပ်။",
    "To check (red in the cart): {what}.": "စစ်ရန် (ခြင်းထဲ အနီရောင်): {what}။",
    "Order #{no} is {status}.": "အော်ဒါ #{no} — {status}။", "Cancels the {status} order ({total} ကျပ်).": "{status} အော်ဒါ ({total} ကျပ်) ကို ပယ်မယ်။",
    "Removes {n} item(s); new total {total} ကျပ်.": "{n} ခု ဖယ်မယ် — စုစုပေါင်းအသစ် {total} ကျပ်။",
    "FAQ “{title}” (keywords: {words}).": "FAQ “{title}” (သော့ချက်: {words})။", "Saves: {what}.": "သိမ်းမယ်: {what}။",
    "Counts as agreement: cart confirmed.": "သဘောတူတယ်လို့ ယူမယ် — ခြင်း အတည်ပြုပြီး။",
    "📘 learned (waiting approval): {what}.": "📘 သင်ထားတာ (အတည်ပြုဖို့ စောင့်နေ): {what}။",
    "“{text}” = we don't sell it": "“{text}” = မရောင်းဘူး", "“{text}” = {what}": "“{text}” = {what}",
    "“{text}” is already {what}: not saved, the owner will decide.": "“{text}” က {what} ဖြစ်နေပြီ — မသိမ်းဘူး၊ ပိုင်ရှင် ဆုံးဖြတ်မယ်။",
    "Too short to learn.": "သင်ဖို့ တိုလွန်းတယ်။", "This answer is not learned.": "ဒီအဖြေကို မသင်ဘူး။",
    "📘 “{text}” = {what}": "📘 “{text}” = {what}", "⚠️ “{text}” is already {what}: not saved, the owner will decide.":
        "⚠️ “{text}” က {what} ဖြစ်နေပြီ — မသိမ်းဘူး၊ ပိုင်ရှင် ဆုံးဖြတ်မယ်။",

    # ---------- practice ----------
    "Practice mode: nothing is saved, nothing is sent.": "လေ့ကျင့်ခန်း — ဘာမှ မသိမ်းဘူး၊ ဘာမှ မပို့ဘူး။",
    "Message {n} of {total}": "စာ {total} စောင်ထဲက {n}",
    "You get {n} practice messages, like real customers write. For each one, do what you would do in the inbox: tap the button if the app's reply is right; on a card, check what the app understood, then ✅ send, ✏️ change or 🙅 do nothing.":
        "ဖောက်သည်တွေ တကယ်ရေးသလို လေ့ကျင့်စာ {n} စောင် ရမယ်။ တစ်စောင်ချင်းမှာ စာဝင်ထဲ လုပ်သလို လုပ်ပါ — App ရဲ့ ဖြေစာ မှန်ရင် ခလုတ်နှိပ်ပါ၊ ကတ်ပေါ်လာရင် App နားလည်တာကို စစ်ပြီး ✅ ပို့မယ်၊ ✏️ ပြင်မယ် (သို့) 🙅 ဘာမှမလုပ်နဲ့ ကို နှိပ်ပါ။",
    "After each answer you see if it was right and what the customer would get.": "ဖြေပြီးတိုင်း မှန်မမှန်နဲ့ ဖောက်သည် ရမယ့်စာကို ပြမယ်။",
    "Read the staff guide first": "ဝန်ထမ်းလမ်းညွှန် အရင်ဖတ်ပါ", "Practice customer": "လေ့ကျင့်ခန်း ဖောက်သည်",
    "The app is not sure. Check its answer like in the inbox.": "App မသေချာဘူး။ စာဝင်ထဲလိုပဲ သူ့အဖြေကို စစ်ပါ။",
    "The app understood:": "App နားလည်တာ:", "The app understood": "App နားလည်တာ",
    "This is wrong — don't send": "ဒါ မှားနေတယ် — မပို့နဲ့", "Check the product, size and price before you tap.": "မနှိပ်ခင် ပစ္စည်း၊ ဆိုဒ်နဲ့ ဈေး စစ်ပါ။",
    "The app can't answer this one by itself. In the real inbox you would open the chat and reply yourself.":
        "ဒီစာကို App က ကိုယ်တိုင် မဖြေနိုင်ဘူး။ တကယ့်စာဝင်မှာဆိုရင် စကားပြောဖွင့်ပြီး ကိုယ်တိုင် ဖြေရမယ်။",
    "Right!": "မှန်တယ်!", "Not right": "မမှန်ဘူး", "Right answer": "မှန်တဲ့အဖြေ", "Your answer": "ကိုယ့်အဖြေ",
    "so tapping was right.": "ဒါကြောင့် နှိပ်တာ မှန်တယ်။",
    "so the button was wrong: don't tap, answer the card or reply yourself.": "ဒါကြောင့် ခလုတ်က မှားတယ် — မနှိပ်နဲ့၊ ကတ်ဖြေပါ (သို့) ကိုယ်တိုင် ဖြေပါ။",
    "The customer would get (practice — not sent):": "ဖောက်သည် ရမယ့်စာ (လေ့ကျင့်ခန်း — မပို့ပါ):",
    "Practice messages: try the buttons and the check cards. Nothing is saved and nothing is sent to anyone.":
        "လေ့ကျင့်စာတွေ — ခလုတ်တွေနဲ့ စစ်ပြီးဖြေတဲ့ ကတ်တွေ စမ်းကြည့်ပါ။ ဘာမှ မသိမ်းဘူး၊ ဘယ်သူ့ဆီမှ မပို့ဘူး။",

    # reply template names (Settings > Reply templates)
    "Greeting (added in front if we haven't messaged them for 6 h)": "နှုတ်ဆက်စာ (၆ နာရီအတွင်း စာမပို့ရသေးရင် ရှေ့မှာ ထည့်)",
    "Price: one size": "ဈေး: ဆိုဒ်တစ်ခု", "Price: all sizes – first line": "ဈေး: ဆိုဒ်အားလုံး – ပထမစာကြောင်း",
    "Price: all sizes – one line per size": "ဈေး: ဆိုဒ်အားလုံး – ဆိုဒ်တစ်ခု တစ်ကြောင်း",
    "Cart / order: one line per item": "ခြင်း / အော်ဒါ: ပစ္စည်းတစ်ခု တစ်ကြောင်း", "Cart: total line": "ခြင်း: စုစုပေါင်း စာကြောင်း",
    "Cart list: last line when we have no phone yet": "ခြင်းစာရင်း: ဖုန်းမရှိသေးရင် နောက်ဆုံးစာကြောင်း",
    "Cart list: last line for a customer with saved phone + address": "ခြင်းစာရင်း: ဖုန်း + လိပ်စာ သိမ်းထားတဲ့ ဖောက်သည်အတွက် နောက်ဆုံးစာကြောင်း",
    "Cart: items we must check (not in the list / no price)": "ခြင်း: စစ်ရမယ့် ပစ္စည်း (စာရင်းထဲမရှိ / ဈေးမရှိ)",
    "Ask phone number": "ဖုန်းနံပါတ် မေး", "Phone received, ask address": "ဖုန်းရပြီ၊ လိပ်စာ မေး",
    "Another phone number added": "ဖုန်းနံပါတ် နောက်တစ်ခု ထည့်ပြီး", "Payment info: total line": "ငွေလွှဲအချက်အလက်: စုစုပေါင်း စာကြောင်း",
    "Payment info: one line per payment method": "ငွေလွှဲအချက်အလက်: ငွေပေးနည်းတစ်ခု တစ်ကြောင်း",
    "Payment info: last line": "ငွေလွှဲအချက်အလက်: နောက်ဆုံးစာကြောင်း", "Several photos sent at once": "ပုံအများကြီး တစ်ခါတည်း ပို့ရင်",
    "Payment approved: order confirmation": "ငွေလွှဲ အတည်ပြုပြီး: အော်ဒါ အတည်ပြုစာ",
    "Payment rejected: money not received": "ငွေလွှဲ ငြင်း: ငွေမရောက်", "Payment rejected: wrong screenshot": "ငွေလွှဲ ငြင်း: screenshot မှား",
    "Payment rejected: amount too low": "ငွေလွှဲ ငြင်း: ငွေနည်း", "Out of stock": "ပစ္စည်းကုန်",
    "One asked item we don't have (added to the reply)": "မေးတဲ့ထဲက မရှိတဲ့ ပစ္စည်းတစ်ခု (ဖြေစာထဲ ထည့်)",
    "Product we don't have": "မရှိတဲ့ ပစ္စည်း",
    "Order sent out ({deli_line} = the Deli line below, only when given)": "အော်ဒါ ပို့လိုက်ပြီ ({deli_line} = အောက်က ပို့သူစာကြောင်း၊ ထည့်ထားမှ)",
    "Deli line (own line; only when a deli name or phone is given)": "ပို့သူ စာကြောင်း (ပို့သူ နာမည် (သို့) ဖုန်း ထည့်ထားမှ)",
    "Order delivered: thank-you (only if switched on in Orders & payments)": "အော်ဒါ ရောက်ပြီ: ကျေးဇူးတင်စာ (အော်ဒါနဲ့ ငွေလွှဲ ဆက်တင်မှာ ဖွင့်ထားမှ)",
    "“When will it arrive?” – order paid / packed": "“ဘယ်တော့ရောက်မလဲ?” – ငွေချေပြီး / ထုပ်ပြီး",
    "“When will it arrive?” – order sent out": "“ဘယ်တော့ရောက်မလဲ?” – ပို့လိုက်ပြီ",
    "Payment reminder (once, when no screenshot came)": "ငွေလွှဲ သတိပေးစာ (screenshot မရောက်ရင် တစ်ခါ)",
    "Order cancelled because no payment came": "ငွေမလွှဲလို့ အော်ဒါ ပယ်",
    "“The previous one”: line added to the cart list when we found one item": "“အရင်ကဟာ”: တစ်ခုတွေ့ရင် ခြင်းစာရင်းထဲ ထည့်တဲ့ စာကြောင်း",
    "“The previous one”: several earlier items – ask which ({options} = numbered lines)":
        "“အရင်ကဟာ”: အရင်ကဟာ အများကြီး – ဘယ်ဟာလဲ မေး ({options} = နံပါတ်တပ် စာကြောင်းများ)",
    "Customer cancelled the order": "ဖောက်သည်က အော်ဒါ ပယ်",
    # AI page + AI on cards / Needs you (docs/SPEC-v4.6-ai.md)
    "AI": "AI", "AI helper": "AI အကူ", "AI calls": "AI ခေါ်ခဲ့တာ", "Mode": "မုဒ်", "Model": "မော်ဒယ်",
    "Reasoning": "စဉ်းစားမှု", "Now": "အခု", "Numbers": "ကိန်းဂဏန်းများ", "Evaluation": "စမ်းသပ်စစ်ဆေးချက်",
    "Passed": "အောင်", "Failed": "ကျ", "cost": "ကုန်ကျ", "Cost (USD)": "ကုန်ကျ (USD)", "Accuracy": "မှန်ကန်မှု",
    "Average answer time": "ပျမ်းမျှ ဖြေချိန်", "average answer time": "ပျမ်းမျှ ဖြေချိန်",
    "Accepted unchanged": "မပြင်ဘဲ လက်ခံ", "Corrected by a person": "လူက ပြင်ပေး",
    "Handled automatically by the AI": "AI က အလိုအလျောက် လုပ်ပေး",
    "Errors / refused by our checker": "အမှား / ကိုယ့်စစ်ဆေးချက်က ငြင်း",
    "Not called (limit or budget)": "မခေါ်ဖြစ် (အကန့်အသတ် / ဘတ်ဂျက်)",
    "Answered with learned patterns (no AI needed)": "သင်ထားတာနဲ့ ဖြေပြီး (AI မလို)",
    "Calls per day (limit)": "တစ်ရက် ခေါ်နိုင်တဲ့ အကြိမ် (အများဆုံး)", "Monthly budget (USD)": "တစ်လ ဘတ်ဂျက် (USD)",
    "AUTO: act when at least this sure (0.5-1)": "AUTO: ဒီလောက် သေချာမှ လုပ်မယ် (0.5-1)",
    "Run evaluation": "စမ်းသပ်စစ်ဆေးမယ်", "Running…": "စစ်နေတယ်…", "No evaluation yet.": "မစစ်ရသေးပါ။",
    "Last 50 AI calls": "နောက်ဆုံး AI ခေါ်ခဲ့တာ ၅၀", "No AI calls yet.": "AI မခေါ်ရသေးပါ။",
    "intent + products right": "လုပ်ချင်တာ + ပစ္စည်း မှန်", "wrong products": "ပစ္စည်းမှား", "{n} messages": "စာ {n} စောင်",
    "acts when the AI is at least {p}% sure": "AI က {p}% အထက် သေချာမှ လုပ်မယ်",
    "SHADOW: suggests on teaching cards": "SHADOW: သင်ပေးကတ်မှာ အကြံပြုမယ်",
    "AUTO: acts when sure": "AUTO: သေချာရင် ကိုယ်တိုင်လုပ်မယ်",
    "The AI only reads messages the rules are not sure about. It never writes to customers: replies come from your templates and prices.":
        "AI က စည်းမျဉ်းတွေ မသေချာတဲ့ စာတွေကိုပဲ ဖတ်တယ်။ ဖောက်သည်ဆီ ဘယ်တော့မှ ကိုယ်တိုင် မရေးဘူး — ဖြေစာတွေက ကိုယ့်စာပုံစံ၊ ကိုယ့်ဈေးနှုန်းကပဲ လာတယ်။",
    "OFF: no AI. SHADOW: the AI fills in teaching cards, a person checks. AUTO: when the AI is sure, the app acts by itself with the usual safety rules.":
        "ပိတ်: AI မသုံး။ SHADOW: AI က သင်ပေးကတ်ကို ဖြည့်ပေး၊ လူက စစ်တယ်။ AUTO: AI သေချာရင် ပုံမှန် ဘေးကင်းစည်းမျဉ်းတွေနဲ့ App က ကိုယ်တိုင်လုပ်တယ်။",
    "Runs the test messages (tests/fixtures/ai_eval.csv) against the real AI: costs about one cent. Pass = intent and products at least 90% right and never a wrong product.":
        "စမ်းသပ်စာတွေကို တကယ့် AI နဲ့ စစ်တယ် (ဒေါ်လာ ၁ ဆင့်လောက် ကုန်)။ အောင်ရင် = လုပ်ချင်တာနဲ့ ပစ္စည်း ၉၀% အထက်မှန်ပြီး ပစ္စည်းမှား လုံးဝမရှိ။",
    "Done. The answer goes out in {n} s unless you undo.": "ပြီးပြီ။ ပြန်မဖျက်ရင် {n} စက္ကန့်အတွင်း အဖြေ ပို့မယ်။",
    "Not saved: {why}": "မသိမ်းရသေးပါ: {why}",
    "Not saved: type numbers for the limit, budget and threshold.": "မသိမ်းရသေးပါ: အကန့်အသတ်၊ ဘတ်ဂျက်၊ threshold မှာ ဂဏန်းရိုက်ပါ။",
    "The evaluation is already running.": "စစ်ဆေးချက် လုပ်နေဆဲပါ။",
    "Evaluation started. It takes about 2 minutes; reload this page.": "စစ်ဆေးချက် စပြီ။ ၂ မိနစ်လောက်ကြာမယ် — စာမျက်နှာ ပြန်ဖွင့်ပါ။",
    "🧠 AI is on, but OPENAI_API_KEY is missing in .env. Messages go to Needs you as before.":
        "🧠 AI ဖွင့်ထားပေမယ့် .env ထဲမှာ OPENAI_API_KEY မရှိဘူး။ စာတွေက အရင်လို ကိုယ်တိုင်လုပ်ရန် ထဲ ရောက်မယ်။",
    "🧠 AI stopped working: {why}. Messages go to Needs you as before.":
        "🧠 AI အလုပ်မလုပ်တော့ဘူး: {why}။ စာတွေက အရင်လို ကိုယ်တိုင်လုပ်ရန် ထဲ ရောက်မယ်။",
    "the API key was refused (check OPENAI_API_KEY in .env)": "API key ကို လက်မခံဘူး (.env ထဲက OPENAI_API_KEY စစ်ပါ)",
    "no credit left: add credit in OpenAI Billing": "credit ကုန်ပြီ: OpenAI Billing မှာ credit ထည့်ပါ",
    "OpenAI refuses this country / region": "OpenAI က ဒီနိုင်ငံ / ဒေသကို လက်မခံဘူး",
    "🧠 AI: {errors} of the last {n} calls failed (network / API). See the AI page.":
        "🧠 AI: နောက်ဆုံး {n} ကြိမ်ထဲက {errors} ကြိမ် မအောင်မြင်ဘူး (network / API)။ AI စာမျက်နှာ ကြည့်ပါ။",
    "🧠 AI: daily limit of {n} calls reached. Until tomorrow, unsure messages go to Needs you without AI help.":
        "🧠 AI: တစ်ရက် {n} ကြိမ် ပြည့်ပြီ။ မနက်ဖြန်အထိ မသေချာတဲ့စာတွေ AI အကူမပါဘဲ ကိုယ်တိုင်လုပ်ရန် ထဲ ရောက်မယ်။",
    "🧠 AI: monthly budget of ${n} used up. Raise it on the AI page, or wait for next month.":
        "🧠 AI: တစ်လ ဘတ်ဂျက် ${n} ကုန်ပြီ။ AI စာမျက်နှာမှာ တိုးပါ (သို့) နောက်လ စောင့်ပါ။",
    # SHADOW -> AUTO graduation (docs/SPEC-v4.7-graduation.md)
    "AI was wrong": "AI မှားတယ်", "Save correction": "ပြင်တာ သိမ်းမယ်",
    "Answer again what the customer wanted. It counts as an AI correction; then fix the cart or reply in the chat.":
        "ဖောက်သည် ဘာလိုချင်တာလဲ ပြန်ဖြေပါ။ AI ပြင်ချက်အဖြစ် မှတ်မယ်။ ပြီးရင် Chat ထဲမှာ ခြင်း (သို့) ဖြေစာကို ပြင်ပါ။",
    "Line {n}: which product?": "စာကြောင်း {n}: ဘယ်ပစ္စည်းလဲ?", "What did the customer want?": "ဖောက်သည်က ဘာလုပ်ချင်တာလဲ?",
    "Auto-graduation": "AUTO ကို ကိုယ်တိုင်ပြောင်း", "Graduation progress": "AUTO ဖြစ်ဖို့ အခြေအနေ",
    "Auto-graduate: switch SHADOW → AUTO by itself when the numbers are good":
        "ကိန်းဂဏန်းတွေ ကောင်းရင် SHADOW → AUTO ကို ကိုယ်တိုင် ပြောင်းမယ်",
    "Auto-graduation is OFF: the mode only changes when you switch it.":
        "ကိုယ်တိုင်ပြောင်းခြင်း ပိတ်ထားတယ်: ကိုယ်ပြောင်းမှပဲ မုဒ် ပြောင်းမယ်။",
    "Everything is ✅: the switch to AUTO happens at the next 09:00 check.":
        "အားလုံး ✅: နောက် မနက် ၉ နာရီ စစ်ချိန်မှာ AUTO ပြောင်းမယ်။",
    "Graduation: accuracy at least (%)": "AUTO ဖြစ်ဖို့: မှန်ကန်မှု အနည်းဆုံး (%)",
    "Graduation: at least this many checked suggestions": "AUTO ဖြစ်ဖို့: စစ်ပြီးသား အကြံပြုချက် အနည်းဆုံး",
    "Graduation: at least this many days in SHADOW": "AUTO ဖြစ်ဖို့: SHADOW မှာ အနည်းဆုံး ရက်",
    "In SHADOW, the app switches the AI to AUTO by itself (checked every day at 09:00) when all lines are ✅. In AUTO, a wrong product, low accuracy or many errors switch it back to SHADOW.":
        "SHADOW မှာ စာကြောင်းအားလုံး ✅ ဖြစ်ရင် App က AUTO ကို ကိုယ်တိုင်ပြောင်းတယ် (နေ့တိုင်း မနက် ၉ နာရီ စစ်)။ AUTO မှာ ပစ္စည်းမှား၊ မှန်ကန်မှုနည်း (သို့) အမှားများရင် SHADOW ကို ပြန်ပြောင်းတယ်။",
    "The AI is in AUTO. The safety brake watches it.": "AI က AUTO မှာ ရှိတယ်။ ဘေးကင်းဘရိတ်က စောင့်ကြည့်နေတယ်။",
    "Window since {date}": "{date} ကစပြီး တွက်တယ်",
    "Days in SHADOW": "SHADOW မှာ ရက်", "Checked AI suggestions (14 days)": "စစ်ပြီးသား AI အကြံပြုချက် (၁၄ ရက်)",
    "Accuracy (14 days)": "မှန်ကန်မှု (၁၄ ရက်)", "Wrong products (14 days)": "ပစ္စည်းမှား (၁၄ ရက်)",
    "Errors (7 days)": "အမှား (၇ ရက်)", "{n} more days": "နောက်ထပ် {n} ရက်",
    "{n} more checked suggestions": "နောက်ထပ် စစ်ပြီးသား {n} ခု", "accuracy must reach {p}": "မှန်ကန်မှု {p} ရောက်ရမယ်",
    "no wrong product allowed in 14 days": "၁၄ ရက်အတွင်း ပစ္စည်းမှား မရှိရ", "errors must be under {p}": "အမှား {p} အောက် ဖြစ်ရမယ်",
    "🧠 AI switched to AUTO: accuracy {p} on {n} decisions, {w} wrong products":
        "🧠 AI က AUTO ပြောင်းပြီ: စစ်ချက် {n} ခုမှာ မှန်ကန်မှု {p}၊ ပစ္စည်းမှား {w}",
    "🧠 AI switched back to SHADOW: {why}": "🧠 AI က SHADOW ပြန်ပြောင်းပြီ: {why}",
    "an admin changed the product of an AUTO-handled message": "AUTO ဖြေထားတဲ့စာရဲ့ ပစ္စည်းကို admin က ပြင်လိုက်တယ်",
    "accuracy {p} on the last {n} decided AI results": "နောက်ဆုံး AI ရလဒ် {n} ခုမှာ မှန်ကန်မှု {p}",
    "{p} of the last {n} AI calls failed": "နောက်ဆုံး AI ခေါ်ချက် {n} ခုထဲက {p} မအောင်မြင်",
    "Saved. Auto-graduation is OFF now (you chose the mode yourself); turn it on again below.":
        "သိမ်းပြီး။ ကိုယ်တိုင် ရွေးလိုက်လို့ AUTO ကိုယ်တိုင်ပြောင်းခြင်း ပိတ်လိုက်ပြီ — အောက်မှာ ပြန်ဖွင့်လို့ရတယ်။",
    "Saved as an AI mistake.": "AI အမှားအဖြစ် သိမ်းပြီး။",
    "Fix the cart or reply in the chat (Undo works while the reply has not gone out).":
        "Chat ထဲမှာ ခြင်း (သို့) ဖြေစာ ပြင်ပါ (ဖြေစာ မထွက်သေးရင် ပြန်ဖျက်လို့ရတယ်)။",
    "The AI is back in SHADOW: {why}.": "AI က SHADOW ပြန်ရောက်ပြီ: {why}။",
    "Nothing to correct: this message was not handled by the AI.": "ပြင်စရာ မရှိပါ: ဒီစာကို AI က မဖြေခဲ့ပါ။",
    "Choose a product (or “we don't sell it”) for every line.": "စာကြောင်းတိုင်းအတွက် ပစ္စည်း (သို့) “မရှိဘူး” ရွေးပါ။",
    "Choose what the customer wanted.": "ဖောက်သည် ဘာလိုချင်တာလဲ ရွေးပါ။",
    "Not saved: type numbers for the limits, budget, threshold and graduation rules.":
        "မသိမ်းရသေးပါ: အကန့်အသတ်၊ ဘတ်ဂျက်၊ threshold နဲ့ AUTO စည်းမျဉ်းတွေမှာ ဂဏန်းရိုက်ပါ။",
    "Not saved: Mode: off, shadow or auto.": "မသိမ်းရသေးပါ: မုဒ်က off, shadow, auto ပဲ ရွေးလို့ရတယ်။",
    # changing the address / phone (docs/SPEC-v4.8-change-info.md)
    "Address / phone changes ({n})": "လိပ်စာ / ဖုန်း ပြောင်းခဲ့တာ ({n})",
    "Address changed after the payment photo — check before packing/sending":
        "ငွေလွှဲပုံ ပို့ပြီးမှ လိပ်စာ ပြောင်းထားတယ် — မထုပ်ခင်/မပို့ခင် စစ်ပါ",
    "Order #{no} address changed after payment — check before packing/sending":
        "အော်ဒါ #{no} ငွေချေပြီးမှ လိပ်စာ ပြောင်းထားတယ် — မထုပ်ခင်/မပို့ခင် စစ်ပါ",
    "address changed at {time} (old: {old})": "{time} မှာ လိပ်စာ ပြောင်းထားတယ် (အဟောင်း: {old})",
    "phone changed at {time} (old: {old})": "{time} မှာ ဖုန်း ပြောင်းထားတယ် (အဟောင်း: {old})",
    "checked": "စစ်ပြီး",
    "customer wants to change the address of an order already sent": "ပို့ပြီးသား အော်ဒါရဲ့ လိပ်စာ ပြောင်းချင်တယ်",
    "Customer wants to change the address: ask the new one": "ဖောက်သည်က လိပ်စာ ပြောင်းချင်: အသစ် မေး",
    "Customer wants to change the phone: ask the new one": "ဖောက်သည်က ဖုန်း ပြောင်းချင်: အသစ် မေး",
    "Customer wants to change something (not clear what): ask both": "ဖောက်သည်က တစ်ခုခု ပြောင်းချင် (မရှင်း): နှစ်ခုလုံး မေး",
    "New address saved (before payment info, or alone if it was sent already)":
        "လိပ်စာအသစ် သိမ်းပြီး (ငွေလွှဲအချက်အလက်ရှေ့မှာ၊ ပို့ပြီးသားဆိုရင် ဒီစာကြောင်းပဲ)",
    "New phone saved (before payment info, or alone if it was sent already)":
        "ဖုန်းအသစ် သိမ်းပြီး (ငွေလွှဲအချက်အလက်ရှေ့မှာ၊ ပို့ပြီးသားဆိုရင် ဒီစာကြောင်းပဲ)",
    "Waiting for the new address from the customer": "ဖောက်သည်ဆီက လိပ်စာအသစ် စောင့်နေတယ်",
    "Waiting for the new phone number from the customer": "ဖောက်သည်ဆီက ဖုန်းနံပါတ်အသစ် စောင့်နေတယ်",
    "Waiting for the new address / phone from the customer": "ဖောက်သည်ဆီက လိပ်စာ / ဖုန်း အသစ် စောင့်နေတယ်",
    "📍 Ask for the new address": "📍 လိပ်စာအသစ် မေးမယ်", "📍 Ask for the new phone": "📍 ဖုန်းအသစ် မေးမယ်",
    "📍 Ask for the new address + phone": "📍 လိပ်စာ + ဖုန်း အသစ် မေးမယ်",
    " + confirm the change": " + ပြင်ပြီးကြောင်း ပြော",
    "Not a status change.": "အခြေအနေ ပြောင်းတာ မဟုတ်ပါ။", "Marked as checked.": "စစ်ပြီးလို့ မှတ်ပြီး။",
    # smart greeting (docs/SPEC-v4.9-greeting.md)
    "Reply to a message that is only a greeting (“hi”): no open order": "နှုတ်ဆက်စာ (“hi”) ကို ပြန်ဖြေစာ: အော်ဒါ မရှိ",
    "Reply to “hi”: open cart ({next_step} = the next question: phone / address / same as last time)":
        "“hi” ကို ပြန်ဖြေစာ: ခြင်း ဖွင့်ထား ({next_step} = နောက်မေးခွန်း: ဖုန်း / လိပ်စာ / အရင်အတိုင်းလား)",
    "Reply to “hi”: payment info sent, waiting for the payment": "“hi” ကို ပြန်ဖြေစာ: ငွေလွှဲအချက်အလက် ပို့ပြီး၊ ငွေစောင့်နေ",
    "Reply to “hi”: payment screenshot received, not checked yet": "“hi” ကို ပြန်ဖြေစာ: ငွေလွှဲပုံ ရပြီ၊ မစစ်ရသေး",
    "Reply to “hi”: order paid / packed": "“hi” ကို ပြန်ဖြေစာ: ငွေချေပြီး / ထုပ်ပြီး",
    "Reply to “hi”: order sent out": "“hi” ကို ပြန်ဖြေစာ: ပို့လိုက်ပြီ",
    "Greeting reply again only after this many minutes (a 2nd “hi” sooner waits for a person)":
        "နှုတ်ဆက်စာ ထပ်ဖြေမယ့် မိနစ် (ဒီထက်စောတဲ့ ဒုတိယ “hi” ကို လူက ဖြေမယ်)",
    "Greeting reply again after: 0-{n} minutes.": "နှုတ်ဆက်စာ ထပ်ဖြေမယ့်အချိန်: 0-{n} မိနစ်။",
    # interruptions & locked paid orders (docs/SPEC-v4.10-interruptions.md)
    "Edit locked order": "ပိတ်ထားတဲ့ အော်ဒါ ပြင်မယ်", "Order #{no} locked": "Order #{no} ပိတ်ထားပြီ",
    "Paid orders are locked. Only for a real exception: the change and the reason are kept in Activity. Tell the customer yourself.":
        "ငွေချေပြီး အော်ဒါတွေကို ပိတ်ထားပါတယ်။ တကယ့်ခြွင်းချက်အတွက်ပဲ ပြင်ပါ: ပြင်တာနဲ့ အကြောင်းရင်းကို မှတ်တမ်းမှာ သိမ်းထားမယ်။ ဖောက်သည်ကို ကိုယ်တိုင် ပြောပါ။",
    "Reason (required)": "အကြောင်းရင်း (မဖြစ်မနေ)", "Save the change": "ပြင်တာ သိမ်းမယ်",
    "Resume line (“send the screenshot”, “send your phone”…) after other answers at most every this many minutes":
        "ပြန်ခေါ်စာကြောင်း (“screenshot ပို့ပါ”, “ဖုန်း ပို့ပါ”…) ကို တခြားအဖြေတွေနောက်မှာ ဒီမိနစ်တစ်ခါပဲ ထည့်မယ်",
    "Resume line at most every: 0-{n} minutes.": "ပြန်ခေါ်စာကြောင်း: 0-{n} မိနစ်။",
    "customer wants to change paid Order #{no}: {what}": "ငွေချေပြီး Order #{no} ကို ဖောက်သည်က ပြင်ချင်တယ်: {what}",
    "{what} after the payment screenshot — check it": "ငွေလွှဲပုံ ပို့ပြီးမှ {what} — စစ်ပါ",
    "add items": "ပစ္စည်း ထပ်ထည့်", "add earlier items": "အရင်ကဟာ ထပ်ထည့်", "remove items": "ပစ္စည်း ဖြုတ်",
    "change address / phone": "လိပ်စာ / ဖုန်း ပြောင်း", "new address / phone": "လိပ်စာ / ဖုန်း အသစ်",
    "total changed {time}": "{time} မှာ စုစုပေါင်း ပြောင်းထား",
    "Total changed at {time}: {old} → {new} ကျပ်.": "{time} မှာ စုစုပေါင်း ပြောင်းထား: {old} → {new} ကျပ်။",
    "⏳ waiting payment": "⏳ ငွေလွှဲ စောင့်နေ", "⏳ waiting: address": "⏳ စောင့်နေ: လိပ်စာ",
    "⏳ waiting: new address / phone": "⏳ စောင့်နေ: လိပ်စာ / ဖုန်း အသစ်", "⏳ waiting: phone": "⏳ စောင့်နေ: ဖုန်း",
    "⏳ waiting: same phone & address?": "⏳ စောင့်နေ: ဖုန်း၊ လိပ်စာ အရင်အတိုင်းလား",
    "📷 payment screenshot to check": "📷 စစ်ရမယ့် ငွေလွှဲပုံ",
    "Resume line while waiting for the payment (added after other answers)":
        "ငွေလွှဲ စောင့်နေချိန် ပြန်ခေါ်စာကြောင်း (တခြားအဖြေတွေနောက်မှာ ထည့်)",
    "Payment info again after the order changed: total line": "အော်ဒါ ပြောင်းပြီးနောက် ငွေလွှဲအချက်အလက် ထပ်ပို့: စုစုပေါင်း စာကြောင်း",
    "After a price, while waiting for the payment: offer to add it": "ငွေလွှဲ စောင့်နေချိန် ဈေးပြောပြီး: ထည့်ပေးရမလား မေး",
    "“I paid” without a screenshot": "screenshot မပါဘဲ “ငွေလွှဲပြီးပြီ”",
    "We must check first (unknown item, or a change after the payment screenshot)":
        "အရင် စစ်ရမယ် (မသိတဲ့ပစ္စည်း၊ ဒါမှမဟုတ် ငွေလွှဲပုံ ပို့ပြီးမှ ပြောင်းတာ)",
    "Paid order is locked: the new items become a NEW order (first line)":
        "ငွေချေပြီး အော်ဒါ ပိတ်ထား: ပစ္စည်းအသစ်တွေက အော်ဒါအသစ် (ပထမစာကြောင်း)",
    "Paid order is locked: the customer asked to change it": "ငွေချေပြီး အော်ဒါ ပိတ်ထား: ဖောက်သည်က ပြင်ချင်တယ်",
    "Order #{no} changed (owner). Tell the customer yourself if needed.": "Order #{no} ပြင်ပြီး (ပိုင်ရှင်)။ လိုရင် ဖောက်သည်ကို ကိုယ်တိုင် ပြောပါ။",
    "Not saved: write the reason.": "မသိမ်းရသေး: အကြောင်းရင်း ရေးပါ။",
    # AI-first inbox (docs/SPEC-v4.11-ai-first.md)
    "AUTO since {date}": "{date} ကစပြီး AUTO", "owner skipped shadow": "ပိုင်ရှင်က SHADOW ကို ကျော်ခဲ့",
    "safety brake ON": "အန္တရာယ်ကင်း ဘရိတ် ဖွင့်ထား",
    "One message removes and adds: line for each removed item": "တစ်စာထဲမှာ ဖြုတ်ပြီး ထည့်: ဖြုတ်လိုက်တဲ့ ပစ္စည်းတစ်ခုချင်းအတွက် စာကြောင်း",
    "Nothing left in the cart after removing": "ဖြုတ်ပြီးနောက် ခြင်းထဲ ဘာမှမကျန်",
    "A name that fits 2-3 products: ask the customer to choose ({options} = numbered lines)":
        "ပစ္စည်း ၂-၃ ခုနဲ့ ကိုက်တဲ့ နာမည်: ဖောက်သည်ကို ရွေးခိုင်းမယ် ({options} = နံပါတ်တပ်ထားတဲ့ စာကြောင်းများ)",
    "Undo dismiss": "ဖယ်ထားတာ ပြန်ဖျက်မယ်", "Older ({n})": "အဟောင်း ({n})",
    "More than 24 h old, and the customer wrote again since. Payments never move here.":
        "၂၄ နာရီထက် ကြာပြီ၊ ဖောက်သည်က နောက်ထပ် စာရေးထားပြီ။ ငွေလွှဲတွေ ဒီထဲ ဘယ်တော့မှ မရောက်ပါ။",
    "Dismiss all older": "အဟောင်းအားလုံး ဖယ်မယ်", "cart changed + list": "ခြင်း ပြင်ပြီး စာရင်းပို့",
    "asked which product": "ဘယ်ပစ္စည်းလဲ မေးပြီး", "Too late to undo.": "ပြန်ဖျက်ဖို့ နောက်ကျသွားပြီ။",
    "Dismissed {n} older messages. Undo for 60 s.": "အဟောင်း {n} ခု ဖယ်ပြီး။ ၆၀ စက္ကန့်အတွင်း ပြန်ဖျက်လို့ရ။",
    "Undone: the older messages are back.": "ပြန်ဖျက်ပြီး: အဟောင်းတွေ ပြန်ရောက်ပြီ။",
    "Auto-learned": "အလိုအလျောက် သင်ယူပြီး", "{n} this week": "ဒီအပတ် {n} ခု",
    "The AI read the same words the same way {n} times with no correction, so the app now understands them by itself. Remove one if it is wrong.":
        "AI က ဒီစာလုံးတွေကို အမှားမပြင်ရဘဲ {n} ကြိမ် တူတူ နားလည်ခဲ့လို့ app က ကိုယ်တိုင် နားလည်ပါပြီ။ မှားရင် ဖယ်ပါ။",
    # AI address assistant + address gates + screenshot reader (docs/SPEC-v4.12-address-payment-ai.md)
    "invalid address": "လိပ်စာ မမှန်", "valid address": "လိပ်စာ မှန်",
    "No address in the message.": "စာထဲမှာ လိပ်စာ မပါ။",
    "Only words like “address” / “change”, no place.": "“လိပ်စာ” / “ပြောင်း” လို စာလုံးပဲ ပါ၊ နေရာ မပါ။",
    "Too short to be an address.": "လိပ်စာ ဖြစ်ဖို့ တိုလွန်းတယ်။",
    "No township (or city + street).": "မြို့နယ် မပါ (ဒါမှမဟုတ် မြို့ + လမ်း မပါ)။",
    "No city.": "မြို့ မပါ။", "Township not in our list.": "မြို့နယ်စာရင်းထဲမှာ မရှိ။",
    "The AI is not sure about this address.": "AI က ဒီလိပ်စာကို မသေချာ။",
    "The address is not valid: fix it in the cart panel.": "လိပ်စာ မမှန်ပါ: ခြင်း ဘေးကွက်မှာ ပြင်ပါ။",
    "check address": "လိပ်စာ စစ်ရန်", "House no.": "အိမ်နံပါတ်", "Street": "လမ်း", "Ward": "ရပ်ကွက်",
    "Township": "မြို့နယ်", "City": "မြို့", "Landmark": "အမှတ်အသား",
    "Address (fix it if needed: house no., street, township)": "လိပ်စာ (လိုရင် ပြင်ပါ: အိမ်နံပါတ်၊ လမ်း၊ မြို့နယ်)",
    "Save address & continue": "လိပ်စာ သိမ်းပြီး ဆက်လုပ်မယ်", "Ask for the full address": "လိပ်စာ အပြည့်အစုံ တောင်းမယ်",
    "Address saved. The reply goes out in 10 s (Undo in the chat).":
        "လိပ်စာ သိမ်းပြီး။ ပြန်စာ ၁၀ စက္ကန့်အတွင်း ထွက်မယ် (chat ထဲမှာ ပြန်ဖျက်လို့ရ)။",
    "Asked for the full address. It goes out in 10 s (Cancel in the chat).":
        "လိပ်စာ အပြည့်အစုံ တောင်းပြီး။ ၁၀ စက္ကန့်အတွင်း ထွက်မယ် (chat ထဲမှာ ပယ်လို့ရ)။",
    "Address without the township: ask it": "မြို့နယ် မပါတဲ့ လိပ်စာ: မြို့နယ် မေးမယ်",
    "Address without the city: ask it": "မြို့ မပါတဲ့ လိပ်စာ: မြို့ မေးမယ်",
    "The address is not clear: ask for the full address (button on the check-address card)":
        "လိပ်စာ မရှင်း: လိပ်စာ အပြည့်အစုံ တောင်းမယ် (လိပ်စာစစ် ကတ်ပေါ်က ခလုတ်)",
    "📍 Ask the township": "📍 မြို့နယ် မေးမယ်", "📍 Ask the city": "📍 မြို့ မေးမယ်",
    "✅ 📍 Ask the township": "✅ 📍 မြို့နယ် မေးမယ်", "✅ 📍 Ask the city": "✅ 📍 မြို့ မေးမယ်",
    "📞 Save phone & 📍 Ask the township": "📞 ဖုန်းသိမ်း & 📍 မြို့နယ် မေးမယ်",
    "✅ 📞 Save phone & 📍 Ask the township": "✅ 📞 ဖုန်းသိမ်း & 📍 မြို့နယ် မေးမယ်",
    "Address without the {what} ({address}): kept 24 h; the answer completes it.":
        "{what} မပါတဲ့ လိပ်စာ ({address}): ၂၄ နာရီ သိမ်းထား၊ အဖြေနဲ့ ပြည့်စုံမယ်။",
    "township": "မြို့နယ်", "city": "မြို့",
    "Approving is blocked until the address is valid.": "လိပ်စာ မှန်မှ အတည်ပြုလို့ ရမယ်။",
    "The address is not valid: fix it on this card.": "လိပ်စာ မမှန်ပါ: ဒီကတ်ပေါ်မှာ ပြင်ပါ။",
    "From the screenshot": "screenshot ထဲက", "to": "သို့", "not a payment receipt": "ငွေလွှဲ ပြေစာ မဟုတ်",
    "Amount, receiver and time match.": "ပမာဏ၊ လက်ခံသူ၊ အချိန် ကိုက်ညီတယ်။",
    "The AI only reads the picture. Check the money in your KPay / AYA app before approving.":
        "AI က ပုံကိုပဲ ဖတ်တာပါ။ အတည်မပြုခင် KPay / AYA app ထဲမှာ ငွေဝင်မဝင် စစ်ပါ။",
    "Reading the screenshot…": "screenshot ကို ဖတ်နေတယ်…",
    "Could not read the screenshot; check it yourself.": "screenshot ကို မဖတ်နိုင်ပါ၊ ကိုယ်တိုင် စစ်ပါ။",
    "from the screenshot: compare it with your KPay / AYA history": "screenshot ထဲက: KPay / AYA မှတ်တမ်းနဲ့ တိုက်စစ်ပါ",
    "{n} warnings from the screenshot": "screenshot က သတိပေးချက် {n} ခု",
    "The screenshot does not look like a payment receipt (or it is unreadable).":
        "screenshot က ငွေလွှဲ ပြေစာ မဟုတ်ပုံရတယ် (ဒါမှမဟုတ် ဖတ်မရ)။",
    "Screenshot amount {amount} ≠ order total {total} ကျပ်: paid more ({diff} ကျပ် too much).":
        "screenshot ပမာဏ {amount} ≠ အော်ဒါ စုစုပေါင်း {total} ကျပ်: ပိုလွှဲထား ({diff} ကျပ် ပို)။",
    "Screenshot amount {amount} ≠ order total {total} ကျပ်: paid less ({diff} ကျပ် missing).":
        "screenshot ပမာဏ {amount} ≠ အော်ဒါ စုစုပေါင်း {total} ကျပ်: လျော့လွှဲထား ({diff} ကျပ် လို)။",
    "Paid to {who}: not one of our payment accounts.": "{who} ကို လွှဲထား: ဆိုင်ရဲ့ ငွေလက်ခံ အကောင့် မဟုတ်။",
    "Transaction no. {no} from the screenshot was already used for order #{order}.":
        "screenshot ထဲက transaction {no} ကို အော်ဒါ #{order} မှာ သုံးပြီးသား။",
    "Receipt time {time} is before we sent the payment info ({sent}).":
        "ပြေစာ အချိန် {time} က ငွေလွှဲအချက်အလက် ပို့ခဲ့တဲ့ အချိန် ({sent}) မတိုင်ခင်။",
    "Receipt time {time} is more than 3 days old.": "ပြေစာ အချိန် {time} က ၃ ရက်ထက် ကြာပြီ။",
    "Status on the screenshot: “{status}” (not successful).": "screenshot ပေါ်က အခြေအနေ: “{status}” (မအောင်မြင်)။",
    "What the AI may see": "AI ကို ဘာတွေ ပြမလဲ", "Addresses": "လိပ်စာများ", "Payment screenshots": "ငွေလွှဲ screenshot များ",
    "Phone numbers are always masked and customer names are never sent. Both readers use the same daily limit and monthly budget; if the AI fails, the normal manual flow continues.":
        "ဖုန်းနံပါတ်တွေကို အမြဲ ဖုံးထားပြီး ဖောက်သည် နာမည် ဘယ်တော့မှ မပို့ပါ။ နှစ်ခုလုံး နေ့စဉ် ကန့်သတ်ချက်နဲ့ လစဉ် ဘတ်ဂျက် တူတူ သုံးတယ်၊ AI မအောင်မြင်ရင် ပုံမှန် လက်နဲ့လုပ်တဲ့ အဆင့် ဆက်သွားမယ်။",
    "delivery addresses are sent to OpenAI to understand them (house no., street, township). Phones stay masked.":
        "ပို့ရမယ့် လိပ်စာတွေကို နားလည်ဖို့ OpenAI ဆီ ပို့မယ် (အိမ်နံပါတ်၊ လမ်း၊ မြို့နယ်)။ ဖုန်းကို ဖုံးထားမယ်။",
    "screenshots contain names and account numbers. They are sent to OpenAI only after you open the payment card, to read amount, transaction no., receiver and time.":
        "screenshot တွေမှာ နာမည်နဲ့ အကောင့်နံပါတ် ပါတယ်။ ငွေစစ်ကတ် ဖွင့်ပြီးမှသာ ပမာဏ၊ transaction၊ လက်ခံသူ၊ အချိန် ဖတ်ဖို့ OpenAI ဆီ ပို့မယ်။",
    "Model {model} reads screenshots (checked {date}).": "{model} မော်ဒယ်က screenshot ဖတ်နိုင်တယ် ({date} မှာ စစ်ပြီး)။",
    "Screenshot reading is not available with model {model}.": "{model} မော်ဒယ်နဲ့ screenshot ဖတ်လို့ မရပါ။",
    "This month": "ဒီလ", "Addresses read: {n}": "ဖတ်ပြီး လိပ်စာ: {n}", "township / city asked: {n}": "မြို့နယ် / မြို့ မေးပြီး: {n}",
    "not sure → a person checked: {n}": "မသေချာ → လူ စစ်ပြီး: {n}", "Screenshots read: {n}": "ဖတ်ပြီး screenshot: {n}",
    "errors: {n}": "အမှား: {n}", "paid more": "ပိုလွှဲ", "paid less": "လျော့လွှဲ", "other receiver": "လက်ခံသူ မှား",
    "transaction no. used before": "transaction ထပ်", "before the payment info": "အချိန် စောနေ",
    "older than 3 days": "၃ ရက်ကျော်", "not successful": "မအောင်မြင်", "not a receipt": "ပြေစာ မဟုတ်",
    # docs/SPEC-v4.13-hotfix.md
    "customer waiting": "ဖောက်သည် စောင့်နေ", "“please wait” sent at {time}": "{time} မှာ “ခဏစောင့်” ပို့ပြီး",
    "Nobody could answer within 60 s: please wait (at most every 10 min)":
        "၆၀ စက္ကန့်အတွင်း ဘယ်သူမှ မဖြေနိုင်: ခဏစောင့်ခိုင်း (၁၀ မိနစ်မှာ အများဆုံး တစ်ခါ)",
}
