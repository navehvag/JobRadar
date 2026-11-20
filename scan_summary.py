"""Per-scan status: which sources failed, and a summary message posted BEFORE the jobs.

Every scan (also one with no new jobs) posts:
  - Telegram: one message — "Scan 12:05 — 7 new jobs (2 ⭐)" or "no new jobs", with per-CV counts
  - Discord:  one message in EVERY channel — "3 new jobs in this channel" or "no new jobs for this
              category in this scan"
Both start with a ⚠️ line when a source failed: an error, a timeout, or 0 jobs from a source
that normally returns jobs (a silent block looks like that).

The per-source counts are kept in scan_log.json as entries with job_id "_sources", so the
history is on GitHub:   py scan_summary.py   (last 10 scans, per source)
"""

import logging
from collections import Counter
from datetime import datetime

from scan_log import LOG_FILE, load_log, save_log

logger = logging.getLogger(__name__)

SOURCES_ID = "_sources"
HISTORY_SCANS = 8  # a 0 is suspicious when the source returned jobs in one of the last N scans


def source_history(path: str = LOG_FILE) -> list[dict]:
    """Per-source reports of earlier scans, oldest first: [{"scan":..., "sources": {name: count|error}}]."""
    return [e for e in load_log(path) if e.get("job_id") == SOURCES_ID]


def record_sources(report: dict, passed: dict | None = None, path: str = LOG_FILE) -> None:
    """report: jobs scraped per source (or the error); passed: how many of them passed the filter."""
    entries = load_log(path)
    entries.append({"scan": datetime.now().strftime("%Y-%m-%d %H:%M"), "job_id": SOURCES_ID, "sources": report,
                    "passed": passed or {}})
    save_log(entries, path)


def source_problems(report: dict, history: list[dict] | None = None) -> list[str]:
    """Human-readable problems: errors / timeouts, and 0 jobs from a source that usually has some."""
    recent = (history or [])[-HISTORY_SCANS:]
    problems = []
    for name, value in report.items():
        if isinstance(value, str):  # "ERROR: ..." / "TIMEOUT (420s)"
            problems.append(f"{name}: {value[:120]}")
        elif value == 0:
            usual = [h["sources"].get(name) for h in recent if isinstance(h["sources"].get(name), int)]
            if any(usual):
                problems.append(f"{name}: 0 jobs (usually ~{max(usual)}) — blocked or site changed?")
    return problems


def _warning(problems: list[str]) -> str:
    return ("⚠️ Sources with no data this scan:\n" + "\n".join(f"• {p}" for p in problems)) if problems else ""


def telegram_text(jobs: list[dict], problems: list[str], scan: str) -> str:
    lines = []
    if problems:
        lines.append(_warning(problems))
    if jobs:
        stars = sum(1 for j in jobs if j.get("Highlight"))
        lines.append(f"🔎 Scan {scan} — {len(jobs)} new job{'s' if len(jobs) != 1 else ''}"
                     + (f" ({stars} ⭐ added to the apply queue)" if stars else ""))
        per_type = Counter(j.get("Job Type") or j.get("Category") or "?" for j in jobs)
        lines.append(" · ".join(f"{t} {n}" for t, n in per_type.most_common()))
    else:
        lines.append(f"🔎 Scan {scan} — no new jobs found.")
    return "\n".join(lines)


def discord_text(count: int, stars: int, problems: list[str], scan: str) -> str:
    if count:
        head = f"🔎 **Scan {scan}** — {count} new job{'s' if count != 1 else ''} in this channel" + (f" ({stars} ⭐)" if stars else "")
    else:
        head = f"🔎 **Scan {scan}** — no new jobs for this category in this scan."
    warn = _warning(problems)
    return f"{warn}\n{head}" if warn else head


def scan_label() -> str:
    return datetime.now().strftime("%d/%m %H:%M")


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    hist = source_history()[-10:]
    if not hist:
        print("No source reports yet (they are recorded from the next scan on).")
        sys.exit(0)
    names = list(dict.fromkeys(n for h in hist for n in h["sources"]))
    print("scraped/passed filter per source")
    print(f"{'source':28s}" + "".join(f"{h['scan'][5:]:>13s}" for h in hist))
    for n in names:
        cells = []
        for h in hist:
            v = h["sources"].get(n, "")
            p = (h.get("passed") or {}).get(n)
            v = 'ERR' if isinstance(v, str) and v.startswith('ERROR') else 'T/O' if isinstance(v, str) and v.startswith('TIMEOUT') else v
            cells.append(f"{(f'{v}/{p}' if p is not None else str(v)):>13}")
        print(f"{n[:27]:28s}" + "".join(cells))
