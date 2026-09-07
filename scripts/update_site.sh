#!/bin/bash
# update_site.sh — Regenerate screening data, rebuild the Astro site, and deploy.
# Run from the stock-web-pages repo root.
#
# Usage: bash scripts/update_site.sh [--push] [--deploy]
#   --push:   commit dependency/data changes to main; GitHub Actions deploys gh-pages
#   --deploy: direct Cloudflare Pages deploy (requires a verified Cloudflare token)
#   both:     do both (only when direct Cloudflare credentials are verified)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -n "$(git status --porcelain=v1)" ]]; then
    echo "❌ Refusing to run: repository has pre-existing changes or staged files."
    git status --short
    exit 1
fi

echo "=== Step 1: Install the locked dependency tree ==="
npm ci

echo ""
echo "=== Step 2: Repair non-breaking npm vulnerabilities before any push ==="
# Major dependency upgrades are reviewed and pinned separately. Daily runs use
# the safe fixer; if a new vulnerability needs a breaking upgrade, this command
# fails and the pipeline stops before any commit or push.
npm audit fix

echo ""
echo "=== Step 3: Reinstall after audit fix ==="
npm ci

echo ""
echo "=== Step 4: Fail closed if any npm vulnerability remains ==="
npm audit

echo ""
echo "=== Step 5: Build screener_history.json (incl. value scores) ==="
python3 scripts/build_screener_history.py

echo ""
echo "=== Step 6: Build Astro site ==="
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
    echo "=== Step 7: Commit to main ==="
    stage_if_present() {
        local path
        for path in "$@"; do
            if [[ -e "$path" ]]; then
                git add -- "$path"
            fi
        done
    }
    stage_if_present .astro/content.d.ts package.json package-lock.json \
        src/data/screener_history.json data/value_scores_cache.json dist/ scripts/
    echo "Staged files:"
    git diff --cached --name-only
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
    echo "=== Step 8: Deploy to Cloudflare Pages (production) ==="
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
