#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOG_DIR="$ROOT_DIR/reports"
LOG_FILE="$LOG_DIR/ci_daily_automation.log"
mkdir -p "$LOG_DIR"

{
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Starting daily AFib CI automation"

  if [[ ! -d .venv ]]; then
    echo "Missing .venv. Run: bash scripts/setup_playwright.sh"
    exit 1
  fi

  source .venv/bin/activate

  # Pull latest to avoid push conflicts. Autostash prevents abort on local edits.
  if ! git pull --rebase --autostash origin main; then
    echo "Warning: git pull failed, continuing with local state."
  fi

  if ! python scripts/ci_capture_playwright.py \
    --days 10 \
    --max-queries 8 \
    --direct-sources 8 \
    --headless \
    --output data/ci_manual_urls.txt; then
    echo "Warning: Playwright capture failed; using existing data/ci_manual_urls.txt"
  fi

  if [[ ! -f data/ci_manual_urls.txt ]]; then
    echo "No input file available at data/ci_manual_urls.txt; exiting."
    exit 1
  fi

  python scripts/ci_from_urls.py \
    --input data/ci_manual_urls.txt \
    --output reports/ci_manual_scan.md \
    --days 10

  CHANGED_TARGETS="$(git status --porcelain -- data/ci_manual_urls.txt reports/ci_manual_scan.md)"
  if [[ -z "$CHANGED_TARGETS" ]]; then
    echo "No CI changes to commit."
    exit 0
  fi

  STAMP="$(date +%Y-%m-%d)"
  git add data/ci_manual_urls.txt reports/ci_manual_scan.md
  git commit -m "Daily AFib CI scan ${STAMP}"
  git push origin main

  echo "Daily AFib CI automation finished and pushed."
} >> "$LOG_FILE" 2>&1
