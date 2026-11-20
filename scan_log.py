"""Score log: every job a scan sends, with its score and why — including the ones below apply_score.

apply_queue.json only keeps jobs that scored >= apply_score, so without this file the score of a
low-ranked job (and the reason for it) lived only in Discord / Telegram. Each entry:

    {"scan": "2026-10-28 18:04", "job_id": ..., "title": ..., "company": ..., "source": ...,
     "link": ..., "job_type": ..., "score": 18, "matched_skills": ["lab", "-power engineering license", "5y req"],
     "queued": false}

"matched_skills" uses the matcher's notes: a plain name = CV skill the job asks for, "-name" = a gap
(something the job asks for that the CV lacks), "Ny req" = required years, "student role",
"no description", "no engineering context".

Entries older than KEEP_DAYS are dropped. The Pi commits this file with state.json after each scan.

    py scan_log.py                 # last scan, best first
    py scan_log.py --since 2026-10-28
"""

import json
from datetime import datetime, timedelta

LOG_FILE = "scan_log.json"
KEEP_DAYS = 45


def load_log(path: str = LOG_FILE) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_log(entries: list[dict], path: str = LOG_FILE) -> None:
    cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    entries = [e for e in entries if (e.get("scan") or "") >= cutoff]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)


def record_scan(jobs: list[dict], apply_score: int, path: str = LOG_FILE) -> int:
    """Append one entry per scored job of this scan. Returns how many were logged."""
    scan = datetime.now().strftime("%Y-%m-%d %H:%M")
    entries = load_log(path)
    for job in jobs:
        score = job.get("Match Score")
        entries.append({
            "scan": scan,
            "job_id": str(job.get("Job ID")),
            "title": job.get("Job Title"),
            "company": job.get("Company"),
            "source": job.get("Source"),
            "link": job.get("Position Link"),
            "job_type": job.get("Job Type"),
            "score": score,
            "matched_skills": job.get("Matched Skills"),
            "queued": score is not None and score >= apply_score,
        })
    save_log(entries, path)
    return len(jobs)


def merge_logs(saved: list[dict], current: list[dict]) -> list[dict]:
    """Union of two copies (Pi + GitHub), one entry per (scan, job_id), oldest first."""
    merged = {(e.get("scan"), e.get("job_id")): e for e in current}
    for e in saved:
        merged.setdefault((e.get("scan"), e.get("job_id")), e)
    return sorted(merged.values(), key=lambda e: e.get("scan") or "")


if __name__ == "__main__":
    import argparse
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Show logged job scores")
    parser.add_argument("--since", help="show every scan from this date (YYYY-MM-DD); default: the last scan only")
    args = parser.parse_args()

    log = [e for e in load_log() if e.get("job_id") != "_sources"]  # per-source reports: py scan_summary.py
    if not log:
        print("scan_log.json is empty")
        sys.exit(0)
    if args.since:
        shown = [e for e in log if (e.get("scan") or "") >= args.since]
    else:
        last = max(e.get("scan") or "" for e in log)
        shown = [e for e in log if e.get("scan") == last]
    for e in sorted(shown, key=lambda e: (e.get("scan") or "", -(e.get("score") or 0))):
        mark = "*" if e.get("queued") else " "
        print(f"{e.get('scan')} {mark}{e.get('score') if e.get('score') is not None else '-':>3}  "
              f"[{e.get('job_type') or '-'}] {e.get('title')} @ {e.get('company')}")
        print(f"        {', '.join(e.get('matched_skills') or [])}")
        print(f"        {e.get('link')}")
