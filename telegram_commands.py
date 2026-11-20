"""Telegram commands, read at the start of every scan (works on GitHub Actions and on a Pi — no
always-on listener needed).

Write to your bot:
    submitted   (or: done / הגשתי / הוגש)
        → every job on your "left for you" list (status needs-manual in apply_queue.json) is marked
          applied, and the bot replies with the list it marked.

Only messages from your own chat (TELEGRAM_CHAT_ID) are used. Messages are picked up by the next
scan (up to a few hours later on the default schedule).

    python telegram_commands.py        # run once (run_scan.sh / the Scan workflow do this)
"""

import os
import re
import sys
from datetime import date

import requests

from apply_queue import load_queue, save_queue
from secrets_env import load_secrets

SUBMITTED = re.compile(r"^\s*(submitted|done|הגשתי|הוגש|הגשתי הכל|הגשתי הכול)\s*[.!]*\s*$", re.I)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_secrets()
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), str(os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not (token and chat):
        return
    api = f"https://api.telegram.org/bot{token}"
    try:
        r = requests.get(f"{api}/getUpdates", params={"timeout": 0, "allowed_updates": '["message"]'}, timeout=30)
        updates = r.json().get("result", []) if r.ok else []
    except Exception as e:
        print(f"telegram commands: {type(e).__name__}")
        return
    if not updates:
        return
    # confirm everything read, so the next scan doesn't see the same messages again
    try:
        requests.get(f"{api}/getUpdates", params={"offset": updates[-1]["update_id"] + 1, "timeout": 0}, timeout=30)
    except Exception:
        pass
    asked = any(str((u.get("message") or {}).get("chat", {}).get("id")) == chat
                and SUBMITTED.match((u.get("message") or {}).get("text") or "") for u in updates)
    if not asked:
        return
    queue = load_queue()
    marked = [i for i in queue if i.get("status") == "needs-manual"]
    for i in marked:
        i["status"] = "applied"
        i["note"] = (i.get("note") or "") + f" | applied by you (Telegram {date.today():%d/%m})"
    save_queue(queue)
    text = ("✅ Marked %d as applied:\n" % len(marked) + "\n".join(
        f"• {i.get('score')} {i.get('title')} — {i.get('company')}" for i in marked)) if marked \
        else "Nothing was waiting for you — the list is already empty."
    print(text)
    try:
        requests.post(f"{api}/sendMessage", json={"chat_id": chat, "text": text[:3900]}, timeout=30)
    except Exception:
        pass


if __name__ == "__main__":
    main()
