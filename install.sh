#!/usr/bin/env bash
# Linux / macOS / Raspberry Pi installer.
#   bash install.sh          venv + packages + setup wizard
#   bash install.sh --cron   also add a cron job (asks for the schedule)
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"

command -v python3 >/dev/null || { echo "python3 is required (3.10+)"; exit 1; }

echo "==> Creating virtual environment (.venv)"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
# Core packages first, so the scanner works even if the optional LinkedIn/Indeed part fails
.venv/bin/pip install -q --prefer-binary requests pyyaml python-dotenv questionary
# python-jobspy needs pandas. On small ARM boards (Pi Zero / Pi 1, armv6) the newest pandas has
# no prebuilt wheel and building it fails — --prefer-binary picks the newest version that has one
# (Raspberry Pi OS gets those from piwheels.org).
if ! .venv/bin/pip install -q --prefer-binary python-jobspy; then
    echo "!! python-jobspy (LinkedIn / Indeed) could not be installed on this machine — those two"
    echo "   sources will be skipped; everything else works. Or run JobRadar on GitHub Actions."
fi
chmod +x run_scan.sh

if [ ! -f config.yaml ]; then
    echo "==> Starting the setup wizard"
    .venv/bin/python setup_wizard.py
else
    echo "==> config.yaml already exists (run '.venv/bin/python setup_wizard.py' to redo it)"
fi

if [ "${1:-}" = "--cron" ]; then
    echo
    echo "Cron schedule. Default: Sun–Thu at 09:00, 12:00, 15:00, 18:00 (this machine's time zone)."
    read -r -p "Hours (comma-separated) [9,12,15,18]: " HOURS; HOURS="${HOURS:-9,12,15,18}"
    read -r -p "Days (cron format, 0=Sun) [0-4]: " DAYS; DAYS="${DAYS:-0-4}"
    LINE="0 $HOURS * * $DAYS cd $DIR && flock -n /tmp/jobradar.lock ./run_scan.sh >> scan.log 2>&1  # jobradar"
    echo "Will add:  $LINE"
    read -r -p "Add it to your crontab? (y/n) [y]: " OK
    if [ "${OK:-y}" = "y" ]; then
        ( crontab -l 2>/dev/null | grep -v '# jobradar' || true ; echo "$LINE" ) | crontab -
        echo "==> Cron installed. Log: $DIR/scan.log"
    fi
fi

echo
echo "Next: .venv/bin/python main.py --dry-run"
