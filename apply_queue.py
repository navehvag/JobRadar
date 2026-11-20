"""Apply queue: jobs that scored high enough against the CV, waiting for your decision.

The scanner only ADDS candidates here (status "pending"). Nothing is submitted automatically:
applications are prepared and sent in a Claude session, one approved job at a time,
which then updates the status to "applied" / "skipped" / "failed".

    py apply_queue.py            # list pending candidates, best first
    py apply_queue.py --all      # include applied / skipped
    py apply_queue.py --open     # on your PC: open every pending job in the browser, then mark each
                                 # one (a = applied, s = skip, Enter = keep pending) — no Claude needed.
                                 # Then: git commit -am "applied" && git push
"""

import json
import logging
from datetime import date

logger = logging.getLogger(__name__)

QUEUE_FILE = "apply_queue.json"


def load_queue(path: str = QUEUE_FILE) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_queue(queue: list[dict], path: str = QUEUE_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def add_candidates(jobs: list[dict], min_score: int, path: str = QUEUE_FILE) -> int:
    """Add jobs with Match Score >= min_score that aren't queued yet. Returns how many were added."""
    queue = load_queue(path)
    known = {str(item["job_id"]) for item in queue}
    added = 0
    for job in jobs:
        if job.get("Match Score", 0) < min_score or str(job.get("Job ID")) in known:
            continue
        location = job.get("Location")
        if isinstance(location, list):
            location = ", ".join(dict.fromkeys(str(x) for x in location if x))
        queue.append({
            "job_id": str(job.get("Job ID")),
            "title": job.get("Job Title"),
            "company": job.get("Company"),
            "location": location,
            "category": job.get("Category"),
            "job_type": job.get("Job Type"),
            "cv": job.get("CV"),
            "source": job.get("Source"),
            "link": job.get("Position Link"),
            "score": job.get("Match Score"),
            "matched_skills": job.get("Matched Skills"),
            "added": date.today().isoformat(),
            "status": "pending",
            "note": "",
        })
        known.add(str(job.get("Job ID")))
        added += 1
    if added:
        save_queue(queue, path)
    logger.info("Apply queue: %d new candidates (score >= %d)", added, min_score)
    return added


def rebuild_pending(jobs: list[dict], min_score: int, path: str = QUEUE_FILE) -> int:
    """Drop every still-pending item and re-add from freshly scored jobs.
    Items already decided (applied / skipped / needs-manual / failed) are kept."""
    queue = [i for i in load_queue(path) if i.get("status") != "pending"]
    save_queue(queue, path)
    return add_candidates(jobs, min_score, path)


if __name__ == "__main__":
    import argparse
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Show the apply queue")
    parser.add_argument("--all", action="store_true", help="Show every status, not only pending")
    parser.add_argument("--open", action="store_true", help="Open pending jobs in the browser and mark them")
    parser.add_argument("--mark-manual-applied", metavar="SOURCE",
                        help="Mark every needs-manual job (the 'left for you' list) as applied; prints them as JSON lines")
    args = parser.parse_args()

    if args.mark_manual_applied:
        import json

        queue = load_queue()
        marked = [i for i in queue if i.get("status") == "needs-manual"]
        for i in marked:
            i["status"] = "applied"
            i["note"] = (i.get("note") or "") + f" | applied by you ({args.mark_manual_applied} {date.today():%d/%m})"
        save_queue(queue)
        for i in sorted(marked, key=lambda i: -(i.get("score") or 0)):
            print(json.dumps({k: i.get(k) for k in ("score", "title", "company", "link")}, ensure_ascii=False))
        sys.exit(0)

    if args.open:
        import webbrowser

        queue = load_queue()
        pending = sorted((i for i in queue if i["status"] == "pending"), key=lambda i: -(i.get("score") or 0))
        if not pending:
            sys.exit("Nothing pending.")
        for i in pending:
            print(f"{i['score']:3d}%  {i['title']} @ {i['company']}   CV: {i.get('cv') or 'cv.pdf'}")
            webbrowser.open_new_tab(i["link"])
        print("\nApply in the browser, then mark each job:")
        for i in pending:
            ans = input(f"  {i['title']} @ {i['company']}  [a = applied / s = skip / Enter = later]: ").strip().lower()
            if ans in ("a", "s"):
                i["status"] = "applied" if ans == "a" else "skipped"
                i["note"] = f"marked {i['status']} {date.today():%d/%m}"
        save_queue(queue)
        print("Saved. Push it:  git commit -am \"apply queue\" && git push")
        sys.exit(0)

    items = [i for i in load_queue() if args.all or i["status"] == "pending"]
    items.sort(key=lambda i: i.get("score") or 0, reverse=True)
    for n, i in enumerate(items, 1):
        print(f"{n:3d}. {i['score']:3d}%  {i['title']} @ {i['company']} | {i.get('location') or '?'}  [{i['status']}]")
        print(f"       {i['link']}")
    print(f"\n{len(items)} jobs")
