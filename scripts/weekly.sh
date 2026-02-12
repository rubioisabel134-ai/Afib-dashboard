#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Running trial update..."
python3 scripts/update.py

echo "Updating weekly intel..."
python3 scripts/update_weekly.py

if git diff --quiet; then
  echo "No data changes detected."
  exit 0
fi

STAMP="$(date +%Y-%m-%d)"
git add data/afib.json data/watchlist.json
git commit -m "Weekly update ${STAMP}"

echo "Pushing to origin/main..."
git push
echo "Done."
