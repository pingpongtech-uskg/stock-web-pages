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
    echo "=== Step 5: Deploy to Cloudflare Pages (production) ==="
    python3 << 'PYEOF'
import subprocess, os
r = subprocess.run(["infisical","secrets","get","Cloudflare_TOKEN","--env","dev","--silent","--plain"], capture_output=True, text=True)
env = os.environ.copy()
env["CLOUDFLARE_API_TOKEN"] = r.stdout.strip()
result = subprocess.run(
    ["npx","wrangler","pages","deploy","dist","--project-name","stock-web-pages","--branch","main","--commit-dirty=true"],
    cwd="/root/stock-web-pages", env=env, capture_output=True, text=True, timeout=120
)
print(result.stdout)
if result.stderr: print(result.stderr[-200:])
PYEOF
    echo "Deployed to Cloudflare Pages."
fi

echo ""
echo "=== Done ==="
echo "Site: https://pingpongtech-uskg.github.io/stock-web-pages/"
