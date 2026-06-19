# 便宜/定存評分 + 排版優化 + 自動推送 — Implementation Plan

> **For Hermes:** Execute sequentially via plan → kanban → review.

**Goal:** 
1. Redesign screening row layout: group 成長/地雷/便宜/定存 into one compact block
2. Add 便宜/定存 scores from StatementDog 健診
3. Auto-push website updates after daily screener

**Architecture:** 
- New `scripts/compute_value_scores.py`: fetch StatementDog 便宜/定存 scores per stock
- Integrate into `build_screener_history.py`: merge value scores into screener_history.json
- Redesign `ScreeningRow.astro`: compact 4-score pill block
- Cron job: add post-screener step to regenerate + push website

**Tech Stack:** Python 3 (data), Astro 6 (frontend), curl (StatementDog scraping)

---

## Task 1: Redesign ScreeningRow layout — 4-score compact block

**Objective:** Group 成長/地雷/便宜/定存 into one horizontal block with pill badges.
No columns should wrap to a second row on desktop.

**Design:**
```
[2105 正新] [投信10日買超 25.56億] [連續買超 0日] [首次上榜 2026-06-02]
  [📊 成長100 地雷100 便宜83 定存80] [股價 29.6] [Z -1.39]
```

**Implementation:**
- Wrap 4 score columns in a `<div class="score-block">` 
- Each score is a `<span class="score-pill">` with colored background
- Green (≥80 pass), no color (<80), muted (— placeholder)
- Remove separate col wrappers; use inline-flex pill layout
- On mobile: pill block can wrap naturally

**Files:**
- Modify: `src/components/ScreeningRow.astro`

---

## Task 2: Build 便宜/定存 score fetcher

**Objective:** Create `scripts/compute_value_scores.py` that fetches StatementDog 健診 scores.

**便宜股 (Cheap Stock) — 6 indicators, from StatementDog:**
1. PE ratio in 5yr lowest 20% ✓/✗
2. PE ratio < 50% of peers ✓/✗
3. PB ratio in 5yr lowest 20% ✓/✗
4. PB ratio < 50% of peers ✓/✗
5. 1yr dividend yield > 6% ✓/✗
6. 5yr avg dividend yield > 6% ✓/✗

**定存股 (Fixed Deposit) — 5 indicators, from StatementDog:**
1. 1yr dividend yield > 6% ✓/✗
2. 5yr avg dividend yield > 6% ✓/✗
3. 5 consecutive years of dividends ✓/✗
4. Payout ratio > 50% in 3 of 5 years ✓/✗
5. 5yr avg payout ratio > 50% ✓/✗

**Data source:** `https://statementdog.com/analysis/{code}`
- Parse the page for 健診 scores
- Cache results in `data/value_scores_cache.json` (24hr TTL)
- Each stock: `{code: {cheap_score: 83, cheap_detail: [...], dividend_score: 80, dividend_detail: [...]}}`

**Implementation:**
- Use `curl` + Python to fetch and parse
- Extract score from the page (look for "通過 X/Y" patterns)
- Fallback: if scraping fails, return null (display "—")

**Files:**
- Create: `scripts/compute_value_scores.py`

---

## Task 3: Integrate value scores into data pipeline

**Objective:** Add cheap_score/dividend_score to screener_history.json entries.

**Changes to `build_screener_history.py`:**
- Import `compute_value_scores` module
- For each active stock code, load cached value scores
- Add fields: `cheap_score`, `dividend_score` (or null if unavailable)
- Archive entries also get these fields (frozen at computation time)

**Files:**
- Modify: `scripts/build_screener_history.py`

---

## Task 4: Auto-push after daily screener

**Objective:** After the daily cronjob screener runs, automatically regenerate website data and push.

**Approach:**
Option A: Add a step to the existing cronjob prompt to run `update_site.sh` + git push
Option B: Create a separate cron job that watches for new report files

**Recommended: Option A** — modify the existing cronjob prompt (d12d8c7991d5) to add:
```
Step N: Update website
Run: bash /root/stock-web-pages/scripts/update_site.sh
Then: cd /root/stock-web-pages && git add -A && git commit -m "daily: screening results $(date +%Y%m%d)" && git push
```

**Files:**
- Modify: cronjob d12d8c7991d5 prompt

---

## Task 5: Build, verify, deploy

- Run full pipeline end-to-end
- Verify all 4 scores display properly
- Verify auto-push works
- Git commit + push
