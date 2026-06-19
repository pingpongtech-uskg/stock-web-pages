#!/bin/bash
# update_site.sh — Regenerate screening data, rebuild the Astro site, and deploy.
# Run from the stock-web-pages repo root.
#
# Usage: bash scripts/update_site.sh [--push] [--deploy]
#   --push:   commit dist/ + data changes to main branch
#   --deploy: push dist/ to gh-pages branch (live site)
#   both:     do both (recommended for daily cron)
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

DO_PUSH=false
DO_DEPLOY=false
for arg in "$@"; do
    case "$arg" in
        --push)   DO_PUSH=true ;;
        --deploy) DO_DEPLOY=true ;;
    esac
done

if $DO_PUSH; then
    echo ""
    echo "=== Step 4: Commit to main ==="
    git add src/data/screener_history.json data/value_scores_cache.json dist/ scripts/ 2>/dev/null || true
    if ! git diff --cached --quiet; then
        git commit -m "daily: screening results $(date +%Y%m%d)"
        git push origin main
        echo "Pushed to main."
    else
        echo "No changes to commit."
    fi
fi

if $DO_DEPLOY; then
    echo ""
    echo "=== Step 5: Deploy to gh-pages ==="
    DEPLOY_DIR=$(mktemp -d)
    cp -r dist/* "$DEPLOY_DIR/"
    echo ".nojekyll" > "$DEPLOY_DIR/.nojekyll"
    cd "$DEPLOY_DIR"
    git init -q
    git checkout -b gh-pages
    git add -A
    git commit -q -m "deploy: $(date +%Y%m%d-%H%M)"
    git push https://github.com/pingpongtech-uskg/stock-web-pages.git gh-pages --force -q
    cd /root/stock-web-pages
    rm -rf "$DEPLOY_DIR"
    echo "Deployed to gh-pages."
fi

echo ""
echo "=== Done ==="
echo "Site: https://pingpongtech-uskg.github.io/stock-web-pages/"
