"""Runs every enabled job source from config.yaml and merges the results.

A source that fails (site down, layout changed) is logged and skipped, so one
broken site never stops the whole scan.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import threading
import time
from collections import Counter

from israeli_boards import scrape_alljobs, scrape_jobmaster
from board_scrapers import scrape_amazon, scrape_hiremetech, scrape_indeed, scrape_mobileye, scrape_workday
from career_scraper import scrape_career_pages
from defense_scrapers import scrape_elbit, scrape_iai, scrape_rafael
from goozali_scraper import scrape_goozali_jobs

logger = logging.getLogger(__name__)


def _enabled(cfg) -> bool:
    if isinstance(cfg, dict):
        return cfg.get("enabled", True)
    return bool(cfg)


def build_source_tasks(config: dict) -> list[tuple[str, callable]]:
    """Return (name, zero-arg function) for every enabled source."""
    src = config.get("sources", {})
    tasks: list[tuple[str, callable]] = []

    if _enabled(src.get("goozali", True)):
        tasks.append(("Goozali", lambda: scrape_goozali_jobs(config["goozali_url"])))

    hm = src.get("hiremetech")
    if _enabled(hm):
        hm = hm if isinstance(hm, dict) else {}
        tasks.append(("HireMeTech", lambda: scrape_hiremetech(
            hm.get("queries", []), hm.get("max_pages", 3), hm.get("posted_days", 14))))

    for key, name, fn in (("rafael", "Rafael", scrape_rafael),
                          ("iai", "IAI / Elta", scrape_iai),
                          ("elbit", "Elbit", scrape_elbit),
                          ("mobileye", "Mobileye", scrape_mobileye)):
        if _enabled(src.get(key)):
            tasks.append((name, fn))

    amazon = src.get("amazon")
    if _enabled(amazon):
        amazon = amazon if isinstance(amazon, dict) else {}
        tasks.append(("Amazon / Annapurna", lambda: scrape_amazon(amazon.get("country", "ISR"))))

    for key, name, fn in (("alljobs", "AllJobs", scrape_alljobs), ("jobmaster", "JobMaster", scrape_jobmaster)):
        board = src.get(key)
        if _enabled(board) and isinstance(board, dict):
            tasks.append((name, lambda b=board, f=fn: f(b.get("queries", []), b.get("max_pages", 2))))

    indeed = src.get("indeed")
    if _enabled(indeed):
        indeed = indeed if isinstance(indeed, dict) else {}
        tasks.append(("Indeed", lambda: scrape_indeed(
            indeed.get("search_terms", []), indeed.get("results_per_term", 50),
            indeed.get("hours_old", 72), indeed.get("sites"))))

    li = src.get("linkedin")
    # LinkedIn is the strictest site: only scan it at the listed hours (Israel time) — fewer requests
    li_hours = (li or {}).get("run_hours") if isinstance(li, dict) else None
    li_now = not li_hours or datetime.now(ZoneInfo("Asia/Jerusalem")).hour in li_hours
    if _enabled(li) and isinstance(li, dict) and li_now:
        tasks.append(("LinkedIn", lambda: scrape_indeed(
            li.get("search_terms", []), li.get("results_per_term", 25),
            li.get("hours_old", 72), ["linkedin"])))

    for site in src.get("workday", []) or []:
        if _enabled(site):
            tasks.append((f"Workday {site['name']}",
                          lambda s=site: scrape_workday(s["name"], s["url"], s.get("max_pages", 60))))

    if config.get("companies"):
        tasks.append(("Career pages", lambda: scrape_career_pages(
            config["companies"], config.get("department_mapping", {}))))

    return tasks


def apply_department_mapping(jobs: list[dict], mapping: dict) -> None:
    """Translate a source's own department name into one of our categories, when mapped."""
    for job in jobs:
        field = job.get("Field")
        if isinstance(field, str) and field in mapping:
            job["Field"] = mapping[field]


def scrape_all(config: dict) -> tuple[list[dict], dict[str, int | str]]:
    """Scrape every enabled source.

    Returns:
        (jobs, report) — report maps source name to job count, or to an error string.
    """
    timeout = config.get("source_timeout_seconds", 180)
    tasks = build_source_tasks(config)
    results: dict[str, list[dict] | Exception] = {}

    def run(name: str, fn) -> None:
        try:
            results[name] = fn()
        except Exception as e:  # keep going — one broken source shouldn't stop the scan
            logger.exception("Source '%s' failed", name)
            results[name] = e

    # All sources run in parallel; each gets `timeout` seconds. A source that hangs
    # is reported as TIMEOUT and abandoned (daemon thread — it won't block exit).
    threads = []
    for name, fn in tasks:
        t = threading.Thread(target=run, args=(name, fn), daemon=True, name=name)
        t.start()
        threads.append((name, t))
    deadline = time.monotonic() + timeout
    for name, t in threads:
        t.join(max(0.0, deadline - time.monotonic()))

    all_jobs: list[dict] = []
    report: dict[str, int | str] = {}
    for name, _ in tasks:
        result = results.get(name)
        if result is None:
            logger.error("Source '%s' timed out after %ds — skipped", name, timeout)
            report[name] = f"TIMEOUT ({timeout}s)"
        elif isinstance(result, Exception):
            report[name] = f"ERROR: {type(result).__name__}: {result}"[:200]
        else:
            for job in result:
                job.setdefault("Source", name)
            all_jobs.extend(result)
            report[name] = len(result)

    apply_department_mapping(all_jobs, config.get("department_mapping", {}))

    # Same posting can show up twice in one source list; keep the first per Job ID
    unique: dict = {}
    for job in all_jobs:
        unique.setdefault(job.get("Job ID"), job)
    return list(unique.values()), report


def format_report(report: dict, filtered: list[dict] | None = None) -> str:
    per_source = Counter(j.get("Source") for j in (filtered or []))
    lines = ["Source                     scraped   passed filter"]
    for name, value in report.items():
        passed = per_source.get(name, 0) if isinstance(value, int) else "-"
        lines.append(f"  {name:24s} {str(value):>7s}   {passed}")
    return "\n".join(lines)
