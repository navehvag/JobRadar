"""Gentler request pacing: randomized pauses between requests and a random start delay for
scheduled scans, so the scanner doesn't hit every site at the exact same second each run."""

import logging
import os
import random
import sys
import time

logger = logging.getLogger(__name__)


def pause(base: float) -> None:
    """Sleep base x 0.8–2.0 (never the same gap twice)."""
    time.sleep(base * random.uniform(0.8, 2.0))


def start_jitter(max_minutes: float) -> None:
    """Wait a random 0..max_minutes before a scheduled (cron) scan. Skipped when run by hand
    from a terminal, so a manual ./run_scan.sh starts right away."""
    if max_minutes <= 0 or sys.stdin.isatty() or os.environ.get("GITHUB_ACTIONS"):
        return
    delay = random.uniform(0, max_minutes * 60)
    logger.info("Random start delay: %.1f min", delay / 60)
    time.sleep(delay)
