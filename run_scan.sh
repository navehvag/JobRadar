#!/usr/bin/env bash
# One scheduled scan (what cron runs). Your data (config.yaml, .env, state.json,
# apply_queue.json, scan_log.json, autofill.yaml, cvs/) stays local and is never committed.
#   ./run_scan.sh             normal scan (+ Telegram commands, + auto-submit if enabled)
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

dry=0
[[ " $* " == *" --dry-run "* ]] && dry=1

# "submitted" written to the Telegram bot since the last scan -> mark the left-for-you list applied
[ "$dry" -eq 0 ] && { "$PY" telegram_commands.py || echo "!! telegram commands failed"; }

"$PY" main.py "$@"
status=$?

# Auto-submit clean application forms (config.yaml auto_submit.enabled) — at most 25 minutes
if [ "$dry" -eq 0 ] && "$PY" -c "import yaml,sys; c=yaml.safe_load(open('config.yaml')) or {}; sys.exit(0 if (c.get('auto_submit') or {}).get('enabled') else 1)" 2>/dev/null; then
    echo "==> auto-submit"
    timeout 1500 "$PY" autosubmit.py || echo "!! auto-submit failed or timed out (exit $?)"
fi

echo "===== $(date '+%F %T') scan end (exit $status)"
exit $status
