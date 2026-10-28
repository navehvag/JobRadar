"""Job Scanner — main orchestrator.

Scrape → Filter → Deduplicate → Notify → Save state.
"""

import logging
import os

import yaml

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # Running in CI, env vars set by GitHub Actions

from discord_notifier import notify_jobs
from telegram_notifier import build_targets, notify_jobs_telegram
from job_filter import filter_jobs
from apply_queue import add_candidates, rebuild_pending
from board_scrapers import fetch_workday_descriptions
from israeli_boards import fetch_jobmaster_descriptions
from matcher import score_jobs
from polite import start_jitter
from sources import format_report, scrape_all
from state_manager import filter_new_jobs, job_key, load_state, save_state

logger = logging.getLogger(__name__)


def main(limit: int | None = None, dry_run: bool = False, mark_seen: bool = False, rescore: bool = False) -> None:
    """Run the full job scanner pipeline.

    Args:
        limit: If set, only send this many jobs (useful for testing).
        dry_run: Scrape + filter + print the new jobs, without sending or saving state.
        mark_seen: Save all current matching jobs as already sent, without sending (first run).
        rescore: Score ALL current matching jobs (ignoring state), print the distribution, rebuild the apply queue.
    """
    if load_dotenv:
        load_dotenv()
    # On GitHub Actions every repository secret arrives as one JSON blob (ALL_SECRETS), so any
    # webhook secret name from config.yaml works without listing it in the workflow
    if os.environ.get("ALL_SECRETS"):
        import json
        for k, v in json.loads(os.environ["ALL_SECRETS"]).items():
            if isinstance(v, str) and v and k not in os.environ:
                os.environ[k] = v

    if not os.path.exists("config.yaml"):
        raise SystemExit("config.yaml not found — run `python setup_wizard.py` first.")
    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Discord: category name -> webhook URL
    webhook_map = {}
    discord_cfg = config.get("discord", {"enabled": True})
    if discord_cfg.get("enabled", True):
        for field_name, env_var in (config.get("discord_webhooks") or {}).items():
            url = os.environ.get(env_var)
            if url:
                webhook_map[field_name] = url
            else:
                logger.warning("Missing env var %s for field '%s'", env_var, field_name)
        # one channel per job type (CV folder); a type without a webhook URL yet falls back to its category
        for job_type, env_var in (config.get("discord_type_webhooks") or {}).items():
            url = os.environ.get(env_var)
            if url:
                webhook_map[f"type:{job_type}"] = url
            else:
                logger.info("No URL in %s yet — '%s' jobs go to their category channel", env_var, job_type)
        if os.environ.get("DISCORD_WEBHOOK_DEFAULT"):
            webhook_map["*"] = os.environ["DISCORD_WEBHOOK_DEFAULT"]  # jobs with no own channel
        if webhook_map:
            webhook_map["_keep_category"] = discord_cfg.get("keep_category_channels") or []

    # Telegram: bot token + category -> chat/topic
    tg_cfg = config.get("telegram", {})
    tg_token = os.environ.get(tg_cfg.get("bot_token_env", "TELEGRAM_BOT_TOKEN")) if tg_cfg.get("enabled") else None
    tg_targets = build_targets(tg_cfg) if tg_token else {}
    if tg_cfg.get("enabled") and not tg_targets:
        logger.warning("Telegram enabled but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing in .env")

    if not webhook_map and not tg_targets and not (dry_run or mark_seen or rescore):
        logger.error("No Discord webhooks or Telegram chat configured. Set them in .env")
        return

    # Scheduled runs start at a random minute (scan_jitter_minutes), not exactly on the hour
    if not (dry_run or rescore):
        start_jitter(float(config.get("scan_jitter_minutes", 0)))

    # 1. Scrape all sources
    logger.info("Step 1: Scraping all sources...")
    jobs, report = scrape_all(config)
    logger.info("Total scraped: %d", len(jobs))

    # 2. Filter
    logger.info("Step 2: Filtering jobs...")
    filtered = filter_jobs(jobs, config["filter"])
    print("\n" + format_report(report, filtered) + "\n")

    if rescore:
        _rescore(filtered, config)
        return

    # 3. Deduplicate
    logger.info("Step 3: Checking for new jobs...")
    sent_ids = load_state()
    new_jobs = filter_new_jobs(filtered, sent_ids)

    if not new_jobs:
        logger.info("No new jobs to send. Done!")
        return

    # Score against the CV profile; best matches are sent first
    fetch_workday_descriptions(new_jobs)
    fetch_jobmaster_descriptions(new_jobs)
    score_jobs(new_jobs, config.get("profile"), config.get("job_types"))
    new_jobs.sort(key=lambda j: j.get("Match Score", 0), reverse=True)
    highlight = (config.get("profile") or {}).get("highlight_score", 60)
    for job in new_jobs:
        job["Highlight"] = job.get("Match Score", 0) >= highlight

    apply_score = (config.get("profile") or {}).get("apply_score", 60)

    if mark_seen:
        added = add_candidates(new_jobs, apply_score)
        print(f"{added} jobs with match >= {apply_score}% added to apply_queue.json")
        sent_ids.update(job["Job ID"] for job in new_jobs if job.get("Job ID") is not None)
        sent_ids.update(k for k in map(job_key, new_jobs) if k)
        save_state(sent_ids)
        print(f"Marked {len(new_jobs)} current jobs as seen — from now on only NEW jobs will be sent.")
        return

    # Optional limit for testing (set via --limit flag)
    if limit and len(new_jobs) > limit:
        logger.info("Limiting to %d jobs (out of %d new)", limit, len(new_jobs))
        new_jobs = new_jobs[:limit]

    if dry_run:
        print(f"DRY RUN — {len(new_jobs)} new jobs would be sent:\n")
        for job in new_jobs:
            loc = job.get("Location")
            loc = ", ".join(map(str, loc)) if isinstance(loc, list) else (loc or "?")
            score = job.get("Match Score")
            score = f"{score:3d}% " if score is not None else ""
            print(f"  {score}[{job['Category']} / {job.get('Job Type', '-')}] {job.get('Job Title')} @ {job.get('Company')} | {loc}")
            print(f"      {job.get('Position Link')}")
        return

    # 4. Notify
    sent_count = 0
    if webhook_map:
        logger.info("Step 4a: Sending %d new jobs to Discord...", len(new_jobs))
        sent_count = max(sent_count, notify_jobs(webhook_map, new_jobs))
    if tg_targets:
        logger.info("Step 4b: Sending %d new jobs to Telegram...", len(new_jobs))
        sent_count = max(sent_count, notify_jobs_telegram(tg_token, tg_targets, new_jobs))

    # Strong matches go to the apply queue (reviewed and submitted with Claude, never automatically)
    add_candidates(new_jobs, apply_score)

    # 5. Save state — add the Job IDs of successfully processed jobs
    new_ids = {job["Job ID"] for job in new_jobs if job.get("Job ID") is not None}
    new_ids |= {k for k in map(job_key, new_jobs) if k}  # company+title keys -> no cross-source repeats
    sent_ids.update(new_ids)
    save_state(sent_ids)
    logger.info("Step 5: State saved (%d total sent IDs)", len(sent_ids))

    logger.info("Pipeline complete: %d scraped -> %d filtered -> %d new -> %d sent",
                len(jobs), len(filtered), len(new_jobs), sent_count)


def _rescore(jobs: list[dict], config: dict) -> None:
    """Score every currently open matching job and rebuild the pending part of the apply queue."""
    from collections import Counter

    profile = config.get("profile") or {}
    fetch_workday_descriptions(jobs)
    fetch_jobmaster_descriptions(jobs)
    score_jobs(jobs, profile, config.get("job_types"))
    jobs.sort(key=lambda j: j.get("Match Score", 0), reverse=True)
    apply_score = profile.get("apply_score", 60)

    buckets = Counter(min(j["Match Score"] // 10 * 10, 90) for j in jobs)
    print(f"\nScore distribution ({len(jobs)} jobs):")
    for b in range(90, -1, -10):
        n = buckets.get(b, 0)
        print(f"  {b:3d}-{b + 9 if b < 90 else 100:<3d} {n:4d}  {'#' * min(n, 60)}")

    print("\nTop 40:")
    for job in jobs[:40]:
        print(f"  {job['Match Score']:3d}%  [{job.get('Job Type', '-')}] {job.get('Job Title')} @ {job.get('Company')}  [{', '.join(job['Matched Skills'])}]")

    added = rebuild_pending(jobs, apply_score)
    print(f"\nApply queue rebuilt: {added} pending jobs with match >= {apply_score}%")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="Job Scanner Pipeline")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs to send (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Scrape + filter + print, don't send or save state")
    parser.add_argument("--rescore", action="store_true",
                        help="Score all current matching jobs, print the distribution, rebuild the apply queue")
    parser.add_argument("--mark-seen", action="store_true",
                        help="Mark all current matching jobs as sent without sending (use once, on first run)")
    args = parser.parse_args()

    main(limit=args.limit, dry_run=args.dry_run, mark_seen=args.mark_seen, rescore=args.rescore)
