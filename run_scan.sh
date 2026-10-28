#!/usr/bin/env bash
# One scheduled scan (what cron runs). Your data (config.yaml, .env, state.json,
# apply_queue.json, cvs/) stays local and is never committed.
#   ./run_scan.sh             normal scan
#   ./run_scan.sh --dry-run   print what would be sent
# Set AUTO_UPDATE=1 to `git pull` the latest code before each scan.
set -uo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

echo "===== $(date '+%F %T') scan start"
if [ "${AUTO_UPDATE:-0}" = "1" ]; then
    git pull -q --ff-only || echo "!! git pull failed — scanning with the current code"
fi
"$PY" main.py "$@"
status=$?
echo "===== $(date '+%F %T') scan end (exit $status)"
exit $status
