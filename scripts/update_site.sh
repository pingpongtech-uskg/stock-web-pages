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

# Get Cloudflare token from Infisical using INFISICAL_TOKEN env var
tok = os.environ.get("INFISICAL_TOKEN")
cf_token = None
if tok:
    # If machine identity token is set, use it to get the secret
    env = os.environ.copy()
    env["INFISICAL_TOKEN"] = tok
    r = subprocess.run(
        ["infisical", "secrets", "get", "Cloudflare_TOKEN",
         "--env", "dev", "--silent", "--plain",
         "--projectId", "35ccbcb8-b5ec-44dd-8b62-b1f49120c869"],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode == 0 and r.stdout.strip():
        cf_token = r.stdout.strip()

if not cf_token:
    # Fallback: read from INFISICAL_TOKEN and call infisical run
    r = subprocess.run(
        ["infisical", "run", "--token", tok, "--projectId", "35ccbcb8-b5ec-44dd-8b62-b1f49120c869",
         "--env", "dev", "--", "bash", "-c", "echo $Cloudflare_TOKEN"],
        capture_output=True, text=True, timeout=15
    )
    cf_token = r.stdout.strip().split('\n')[-1] if r.stdout.strip() else None

if not cf_token:
    print("ERROR: Could not get Cloudflare_TOKEN from Infisical")
    exit(1)

env = os.environ.copy()
env["CLOUDFLARE_API_TOKEN"] = cf_token
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
