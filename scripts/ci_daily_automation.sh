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
    --days 10 \
    --verify-page-dates
  echo "Daily AFib CI automation finished (local-only)."
} >> "$LOG_FILE" 2>&1
