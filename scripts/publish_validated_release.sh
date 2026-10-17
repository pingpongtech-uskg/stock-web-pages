#!/usr/bin/env bash
# Publish only validated data, preserving concurrent source changes without force.
set -euo pipefail

git add -- public/data
if [ -f config/tracked_symbols.json ]; then
  git add -- config/tracked_symbols.json
fi
while IFS= read -r -d '' path; do
  case "$path" in
    public/data/*|config/tracked_symbols.json) ;;
    *) echo 'publication_invalid=unrelated_staged_file' >&2; exit 1 ;;
  esac
done < <(git diff --cached --name-only -z)

if git diff --cached --quiet; then
  exit 0
fi
git commit -m 'data: publish daily Taiwan stock snapshot'

for attempt in 1 2 3; do
  git fetch --no-tags origin main
  if ! git rebase FETCH_HEAD; then
    git rebase --abort
    echo 'publication_conflict=concurrent_data_requires_review' >&2
    exit 1
  fi
  if git push origin HEAD:main; then
    exit 0
  fi
done
echo 'publication_failed=bounded_push_attempts_exhausted' >&2
exit 1
