#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  echo "Missing .venv. Run: bash scripts/setup_playwright.sh"
  exit 1
fi

source .venv/bin/activate

python scripts/ci_capture_playwright.py --days 10 --max-queries 8 --output data/ci_manual_urls.txt
python scripts/ci_from_urls.py --input data/ci_manual_urls.txt --output reports/ci_manual_scan.md --days 10

echo "Report generated: $ROOT_DIR/reports/ci_manual_scan.md"
