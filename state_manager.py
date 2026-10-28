"""State manager for tracking already-sent job listings."""

import json
import logging
import re

logger = logging.getLogger(__name__)

STATE_FILE = "state.json"


def load_state(path: str = STATE_FILE) -> set[int | str]:
    """Read state.json and return the set of already-sent Job IDs.
    
    If the file doesn't exist (first run) or is corrupted, return empty set.
    """
    try:
        with open(path, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("State file not found or corrupted, starting fresh.")
        return set()


def save_state(sent_ids: set[int | str], path: str = STATE_FILE) -> None:
    """Write the set of sent Job IDs to state.json."""
    with open(path, "w") as f:
        json.dump(list(sent_ids), f, indent=2)


_COMPANY_NOISE = re.compile(r"\b(ltd|inc|llc|corp|corporation|technologies|technology|group|israel|il)\b")


def job_key(job: dict) -> str | None:
    """Source-independent identity: normalized company + title (e.g. the same job on Goozali and LinkedIn)."""
    norm = lambda s: re.sub(r"[^0-9a-z\u0590-\u05ff]+", "", s)
    title = norm(str(job.get("Job Title") or "").lower())
    company = norm(_COMPANY_NOISE.sub("", str(job.get("Company") or "").lower()))
    return f"k:{company}|{title}" if title and company else None


def filter_new_jobs(jobs: list[dict], sent_ids: set[int | str]) -> list[dict]:
    """Return only jobs not sent before — by Job ID, and by company+title across sources."""
    sent_keys = {s for s in sent_ids if isinstance(s, str) and s.startswith("k:")}
    # jobs already sent under another source's ID (e.g. Goozali) still show up in this scan
    sent_keys |= {job_key(j) for j in jobs if j.get("Job ID") in sent_ids}
    new_jobs, batch_keys = [], set()
    for job in jobs:
        key = job_key(job)
        if job.get("Job ID") in sent_ids or (key and (key in sent_keys or key in batch_keys)):
            continue
        if key:
            batch_keys.add(key)
        new_jobs.append(job)
    logger.info("Dedup: %d jobs -> %d new (%d already sent or duplicates)",
                len(jobs), len(new_jobs), len(jobs) - len(new_jobs))
    return new_jobs


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Quick test: load, add some IDs, save, reload
    state = load_state()
    logger.info("Loaded %d sent IDs", len(state))

    # Simulate sending 3 jobs
    fake_ids = {99991, 99992, 99993}
    state.update(fake_ids)
    save_state(state)
    logger.info("Saved %d IDs (added 3 fake ones)", len(state))

    # Reload and verify
    state2 = load_state()
    logger.info("Reloaded %d IDs — matches: %s", len(state2), state == state2)
