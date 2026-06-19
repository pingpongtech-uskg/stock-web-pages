#!/bin/bash
# update_site.sh — Regenerate screening data and rebuild the Astro site.
# Run from the stock-web-pages repo root.
#
# Usage: bash scripts/update_site.sh [--push]
#   --push: after building, auto git add/commit/push
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Step 1: Build screener_history.json (incl. value scores) ==="
python3 scripts/build_screener_history.py

echo ""
echo "=== Step 2: Install dependencies ==="
npm install --silent

echo ""
echo "=== Step 3: Build Astro site ==="
npm run build

if [[ "${1:-}" == "--push" ]]; then
    echo ""
    echo "=== Step 4: Git commit & push ==="
    git add src/data/screener_history.json data/value_scores_cache.json dist/ scripts/ 2>/dev/null || true
    if ! git diff --cached --quiet; then
        git commit -m "daily: screening results $(date +%Y%m%d)"
        git push
        echo "Pushed to GitHub."
    else
        echo "No changes to commit."
    fi
fi

echo ""
echo "=== Done ==="
echo "Site: https://pingpongtech-uskg.github.io/stock-web-pages/"
