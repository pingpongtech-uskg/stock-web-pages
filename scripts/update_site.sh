#!/bin/bash
# update_site.sh — Regenerate screening data and rebuild the Astro site.
# Run from the stock-web-pages repo root.
#
# Usage: bash scripts/update_site.sh
#   After new daily_trust10_*.json files appear in /root/tw-stock-monitor/output/reports/,
#   run this script to update the screener_history.json and rebuild the static site.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Step 1: Build screener_history.json ==="
python3 scripts/build_screener_history.py

echo ""
echo "=== Step 2: Install dependencies (if needed) ==="
npm install --silent

echo ""
echo "=== Step 3: Build Astro site ==="
npm run build

echo ""
echo "=== Done ==="
echo "Site built to: $(pwd)/dist/"
echo "Next: git add/commit/push or deploy"
