"""Telegram bot notifier for job listings.

Sends each job as a message with a clickable title and an "Apply" button.
Routing per category:
  - One chat for everything (TELEGRAM_CHAT_ID), or
  - A group with Topics enabled, one topic per category (`topics` in config.yaml), or
  - A different chat per category (`chats` in config.yaml: category -> env var).

Setup helper:  py telegram_notifier.py --setup   (prints chat IDs + topic IDs the bot can see)
"""

import html
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

SEND_DELAY = 0.1  # seconds between messages (429s are retried in _call)

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, payload: dict | None = None) -> dict:
    r = requests.post(API.format(token=token, method=method), json=payload or {}, timeout=30)
    data = r.json()
    for _ in range(5):  # fast sending hits 429 now and then — wait as told and retry
        if r.status_code != 429:
            break
        wait = (data.get("parameters") or {}).get("retry_after", 3)
        logger.warning("Rate limited by Telegram, waiting %s s", wait)
        time.sleep(wait + 0.5)
        r = requests.post(API.format(token=token, method=method), json=payload or {}, timeout=30)
        data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
    return data["result"]


def build_message(job: dict) -> tuple[str, dict | None]:
    """Return (HTML text, inline keyboard) for one job."""
    esc = lambda s: html.escape(str(s or ""))
    title = esc(job.get("Job Title") or "Unknown position")
    company = esc(job.get("Company") or "Unknown company")
    link = job.get("Position Link")

    location = job.get("Location")
    if isinstance(location, list):
        location = ", ".join(dict.fromkeys(str(x) for x in location if x))
    exp = job.get("Min Experience (Y)")

    head = f'<a href="{esc(link)}"><b>{title}</b></a>' if link else f"<b>{title}</b>"
    if job.get("Highlight"):
        head = "⭐ " + head
    lines = [head, f"🏢 {company}"]
    if job.get("Match Score") is not None:
        skills = ", ".join(job.get("Matched Skills") or [])
        lines.append(f"🎯 Match {job['Match Score']}%" + (f" · {esc(skills)}" if skills else ""))
    if job.get("Highlight"):
        lines.append("📝 Added to apply queue")
    if location:
        lines.append(f"📍 {esc(location)}")
    if exp is not None:
        lines.append(f"🎓 {esc(exp)}Y experience")
    if job.get("Job Type"):
        lines.append(f"📄 CV: {esc(job['Job Type'])}")
    tags = [str(t) for t in (job.get("Category") or job.get("Field"), job.get("Source")) if t]
    if tags:
        lines.append("🏷 " + esc(" · ".join(tags)))

    keyboard = {"inline_keyboard": [[{"text": "Open job ↗", "url": link}]]} if link else None
    return "\n".join(lines), keyboard


def build_targets(tg_config: dict) -> dict[str, dict]:
    """Map category -> {chat_id, message_thread_id?}; key "*" is the default target."""
    targets: dict[str, dict] = {}
    default_chat = os.environ.get(tg_config.get("chat_id_env", "TELEGRAM_CHAT_ID"))
    if default_chat:
        targets["*"] = {"chat_id": default_chat}
        for category, thread_id in (tg_config.get("topics") or {}).items():
            if thread_id:
                targets[category] = {"chat_id": default_chat, "message_thread_id": int(thread_id)}
    for category, env_var in (tg_config.get("chats") or {}).items():
        chat = os.environ.get(env_var)
        if chat:
            targets[category] = {"chat_id": chat}
        else:
            logger.warning("Missing env var %s for Telegram category '%s'", env_var, category)
    return targets


def notify_jobs_telegram(token: str, targets: dict[str, dict], jobs: list[dict]) -> int:
    """Send jobs to Telegram. Returns the number sent."""
    sent = 0
    for job in jobs:
        category = job.get("Category") or job.get("Field") or ""
        target = targets.get(category) or targets.get("*")
        if not target:
            logger.warning("No Telegram chat for '%s', skipping: %s", category, job.get("Job Title"))
            continue
        text, keyboard = build_message(job)
        payload = {**target, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard:
            payload["reply_markup"] = keyboard
        try:
            _call(token, "sendMessage", payload)
            sent += 1
        except Exception:
            logger.exception("Telegram send failed: %s", job.get("Job Title"))
        time.sleep(SEND_DELAY)
    logger.info("Done: sent %d/%d jobs to Telegram", sent, len(jobs))
    return sent


def setup_helper(token: str) -> None:
    """Print chats/topics the bot has seen. Send a message in the group/topic first."""
    me = _call(token, "getMe")
    print(f"Bot: @{me['username']}\n")
    updates = _call(token, "getUpdates", {"timeout": 0})
    if not updates:
        print("No messages yet. Add the bot to your group (or open a chat with it), send any message,\n"
              "then run this again. In a group with Topics, send one message inside EACH topic.")
        return
    seen = set()
    for u in updates:
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        topic = msg.get("message_thread_id")
        topic_name = ((msg.get("reply_to_message") or {}).get("forum_topic_created") or {}).get("name", "")
        key = (chat.get("id"), topic)
        if not chat or key in seen:
            continue
        seen.add(key)
        name = chat.get("title") or chat.get("username") or chat.get("first_name")
        line = f"chat_id={chat['id']:<16} {chat.get('type'):<11} {name}"
        if topic:
            line += f"   topic_id={topic} {topic_name}"
        print(line)


if __name__ == "__main__":
    import argparse

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Telegram notifier")
    parser.add_argument("--setup", action="store_true", help="Print chat IDs / topic IDs the bot can see")
    parser.add_argument("--test", action="store_true", help="Send one test message per configured category")
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env first")

    if args.setup:
        setup_helper(token)
    else:
        import yaml
        with open("config.yaml", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        targets = build_targets(config.get("telegram", {}))
        categories = list(config["filter"]["categories"])
        test_jobs = [{
            "Job Title": f"Test job — {cat}", "Company": "Job Scanner", "Location": "Tel Aviv",
            "Category": cat, "Source": "test", "Position Link": "https://example.com",
        } for cat in categories]
        notify_jobs_telegram(token, targets, test_jobs)
