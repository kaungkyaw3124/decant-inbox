"""docs/SPEC-v5.0-go-live-pack.md G1: print the chat id(s) of whoever sent /start to the alert bot.

1. Put ALERT_BOT_TOKEN=<token from @BotFather> in .env.  2. Open the bot in Telegram and send /start.
3. Run: .venv/bin/python -m scripts.alert_chat_id   4. Copy your id into ALERT_CHAT_ID= in .env.
"""
from app.alerts import bot

if __name__ == "__main__":
    rows = bot.chat_ids()
    if not rows:
        print("No messages yet: send /start to your bot in Telegram, then run this again.")
    for chat_id, name in rows:
        print(f"ALERT_CHAT_ID={chat_id}   ({name})")
