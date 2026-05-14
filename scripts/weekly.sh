#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMMIT_TARGETS=(
  data/afib.json
  data/ci_date_cache.json
  data/ci_manual_urls.txt
  data/company_press_cache.json
  data/weekly_updates.csv
  reports/ci_manual_scan.md
)

run_step() {
  local label="$1"
  shift
  local start
  local end
  start="$(date +%s)"
  echo "$label..."
  "$@"
  end="$(date +%s)"
  echo "$label completed in $((end - start))s."
}

run_step "Running trial update" python3 scripts/update.py

run_step "Fetching company press releases" python3 scripts/update_news.py

run_step "Updating weekly intel" python3 scripts/update_weekly.py

run_step "Applying weekly updates to cards" python3 scripts/apply_weekly_to_cards.py

if git diff --quiet -- "${COMMIT_TARGETS[@]}"; then
  echo "No data changes detected."
  exit 0
fi

STAMP="$(date +%Y-%m-%d)"
git add "${COMMIT_TARGETS[@]}"
git commit -m "Weekly update ${STAMP}"

echo "Pushing to origin/main..."
git push origin main
echo "Done."
