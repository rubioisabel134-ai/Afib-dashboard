#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: bash scripts/run_conference_scan.sh <ACC|HRS|EHRA|ESC|AHA> [--with-google-news]"
  exit 1
fi

CONFERENCE="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
EXTRA_FLAG="${2:-}"

case "$CONFERENCE" in
  ACC|HRS|EHRA|ESC|AHA)
    ;;
  *)
    echo "Unsupported conference: $CONFERENCE"
    echo "Use one of: ACC, HRS, EHRA, ESC, AHA"
    exit 1
    ;;
esac

echo "Running conference scan for $CONFERENCE..."
python3 scripts/update_news.py --conference-only --conference "$CONFERENCE" --verbose-timing ${EXTRA_FLAG:+$EXTRA_FLAG}

echo "Updating weekly intel..."
python3 scripts/update_weekly.py

echo "Applying weekly updates to cards..."
python3 scripts/apply_weekly_to_cards.py

echo
echo "Conference scan complete for $CONFERENCE."
echo "Review changes with:"
echo "  git diff -- data/weekly_updates.csv data/afib.json"
echo
echo "If the updates look good, push them with:"
echo "  git add data/weekly_updates.csv data/afib.json"
echo "  git commit -m \"Update ${CONFERENCE} conference news\""
echo "  git push origin main"
