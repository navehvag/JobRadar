"""Discord webhook notifier for job listings."""

import logging
import time

import requests

logger = logging.getLogger(__name__)

SEND_DELAY = 0.1  # seconds between messages

EMBED_COLOR = 0x2ECC71  # Green sidebar


def build_embed(job: dict) -> dict:
    """Convert a job listing dict into a Discord embed dict.

    Args:
        job: A job dict from the scraper (with resolved selection names).

    Returns:
        A Discord embed dict ready to be sent via webhook.
    """
    # Handle Location: it's a list like ["Tel Aviv", "Ramat Gan"] or None
    location = job.get("Location")
    if isinstance(location, list):
        location_str = ", ".join(location)
    elif location:
        location_str = str(location)
    else:
        location_str = "Not specified"

    # Handle experience: int or None
    exp = job.get("Min Experience (Y)")
    exp_str = f"{exp}Y" if exp is not None else "Not specified"

    # Truncate description to 200 chars
    description = job.get("Job Description", "")
    if len(description) > 200:
        description = description[:197] + "..."

    # Build the title: "Job Title @ Company"
    title = job.get("Job Title", "Unknown Position")
    company = job.get("Company", "Unknown Company")

    embed = {
        "title": f"{title} @ {company}",
        "color": EMBED_COLOR,
        "fields": [
            {"name": "Category", "value": job.get("Category") or job.get("Field") or "N/A", "inline": True},
            {"name": "CV", "value": job.get("Job Type") or "N/A", "inline": True},
            {"name": "Location", "value": location_str, "inline": True},
            {"name": "Experience", "value": exp_str, "inline": True},
            {"name": "Source", "value": job.get("Source") or job.get("platform") or "N/A", "inline": True},
        ],
        "footer": {"text": f"Job ID: {job.get('Job ID', 'N/A')}"},
    }

    if job.get("Match Score") is not None:
        skills = ", ".join(job.get("Matched Skills") or []) or "—"
        embed["fields"].insert(0, {"name": "Match", "value": f"{job['Match Score']}% · {skills}", "inline": False})
    if job.get("Highlight"):
        embed["title"] = "⭐ " + embed["title"]
        embed["color"] = 0xF1C40F  # gold for strong matches

    # Only add url if Position Link exists (makes title clickable)
    link = job.get("Position Link")
    if link:
        embed["url"] = link

    # Only add description if we have one
    if description:
        embed["description"] = description

    return embed


def send_to_discord(webhook_url: str, embed: dict) -> bool:
    """Send a single embed to a Discord webhook.

    Handles rate limiting: if Discord returns 429 (Too Many Requests),
    waits the amount of time specified in the Retry-After header and
    retries once.

    Args:
        webhook_url: The Discord webhook URL.
        embed: A Discord embed dict (from build_embed).

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    payload = {"embeds": [embed]}

    try:
        response = requests.post(webhook_url, json=payload)

        # 204 = success (Discord returns No Content on webhook posts)
        if response.status_code == 204:
            return True

        # 429 = rate limited — wait as told and retry (up to 5 times; fast sending hits this)
        for _ in range(5):
            if response.status_code != 429:
                break
            retry_after = float(response.json().get("retry_after", 2))
            logger.warning("Rate limited by Discord, waiting %.1f seconds", retry_after)
            time.sleep(retry_after + 0.1)
            response = requests.post(webhook_url, json=payload)
        if response.status_code == 204:
            return True

        logger.error("Discord webhook failed: status %d, body: %s", response.status_code, response.text[:200])
        return False

    except requests.RequestException:
        logger.exception("Failed to send Discord webhook")
        return False


def notify_jobs(webhook_map: dict[str, str], jobs: list[dict]) -> int:
    """Send multiple job listings to Discord, routing each to the right channel.

    Each job is sent to the webhook matching its Field. If a job's field
    has no matching webhook, it is skipped with a warning.

    Args:
        webhook_map: Maps field names to Discord webhook URLs,
                     e.g. {"Software Engineering": "https://discord.com/api/webhooks/..."}.
        jobs: List of job dicts to send.

    Returns:
        Number of jobs successfully sent.
    """
    sent = 0
    skipped = 0
    keep_category = set(webhook_map.get("_keep_category") or [])
    for i, job in enumerate(jobs, start=1):
        field = job.get("Category") or job.get("Field") or ""
        webhook_url = webhook_map.get(field)
        # Route by job type (CV folder) — except default-type jobs in categories that keep their own
        # channel (integration / validation roles get the general CV but their own channel)
        type_url = webhook_map.get(f"type:{job.get('Job Type')}")
        if type_url and not (job.get("Default Type") and field in keep_category):
            webhook_url = type_url
        webhook_url = webhook_url or webhook_map.get("*")

        if not webhook_url:
            logger.warning("No webhook for field '%s', skipping: %s", field, job.get("Job Title"))
            skipped += 1
            continue

        embed = build_embed(job)
        if send_to_discord(webhook_url, embed):
            sent += 1

        if i % 10 == 0:
            logger.info("Progress: sent %d/%d jobs", sent, len(jobs))

        # Small delay between messages (0.1 s; 429 responses are retried above)
        time.sleep(SEND_DELAY)

    logger.info("Done: sent %d/%d jobs to Discord (skipped %d)", sent, len(jobs), skipped)
    return sent


if __name__ == "__main__":
    # Sends one test message to each category's channel, to check the webhooks.
    import os

    import yaml

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    webhook_map = {}
    for field_name, env_var in config["discord_webhooks"].items():
        url = os.environ.get(env_var)
        if url:
            webhook_map[field_name] = url
        else:
            logger.warning("Missing env var %s for '%s'", env_var, field_name)

    test_jobs = [{
        "Job ID": f"test-{i}", "Job Title": f"Test job — {cat}", "Company": "Job Scanner",
        "Location": "Tel Aviv", "Category": cat, "Source": "test", "Position Link": "https://example.com",
    } for i, cat in enumerate(webhook_map)]
    notify_jobs(webhook_map, test_jobs)
