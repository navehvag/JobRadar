"""Send a one-off admin alert (e.g. "the scan couldn't push to GitHub") to Telegram and Discord.

Used by the Scan workflow / run_scan.sh when saving the results keeps failing. Self-contained (plain requests), so it works even if
the push that failed left the repo in an odd state. Reads the bot token / webhooks from .env.

    python notify_admin.py "⚠️ message to send"
"""

import os
import sys

import requests

from secrets_env import load_secrets

load_secrets()

try:
    import yaml
    CONFIG = yaml.safe_load(open("config.yaml", encoding="utf-8")) or {}
except Exception:
    CONFIG = {}

TIMEOUT = 20


def send(message: str) -> list[str]:
    sent = []

    # Telegram: the default chat (TELEGRAM_CHAT_ID)
    tg = CONFIG.get("telegram", {})
    token = os.environ.get(tg.get("bot_token_env", "TELEGRAM_BOT_TOKEN")) if tg.get("enabled", True) else None
    chat = os.environ.get(tg.get("chat_id_env", "TELEGRAM_CHAT_ID"))
    if token and chat:
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": message, "disable_web_page_preview": True}, timeout=TIMEOUT)
            r.raise_for_status()
            sent.append("telegram")
        except Exception as e:
            print(f"telegram alert failed: {type(e).__name__}", file=sys.stderr)

    # Discord: the first configured webhook (one channel is enough for an alert)
    url = next((os.environ[v] for v in sorted(os.environ)
                if v.startswith("DISCORD_WEBHOOK_") and os.environ.get(v)), None)
    if url:
        try:
            r = requests.post(url, json={"content": message[:1990]}, timeout=TIMEOUT)
            r.raise_for_status()
            sent.append("discord")
        except Exception as e:
            print(f"discord alert failed: {type(e).__name__}", file=sys.stderr)

    return sent


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "⚠️ Job scanner alert"
    where = send(msg)
    print("alert sent to: " + (", ".join(where) if where else "nowhere (no Telegram/Discord in .env)"))
