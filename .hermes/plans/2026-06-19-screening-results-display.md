# Screening Results Display — Implementation Plan

> **For Hermes:** Execute tasks sequentially via kanban, verify each before proceeding.

**Goal:** Replace per-stock card view with screening-results table display using real `daily_trust10_*.json` data.

**Architecture:** New data pipeline (`build_screener_history.py`) consolidates all screening reports into `screener_history.json`. New `ScreeningTable.astro` component renders a glass-morphism table. Updated `index.astro` shows Active (flat, sorted by latest上榜日) and Archive (date-grouped collapsible sections).

**Tech Stack:** Python 3 (data pipeline), Astro 6 (frontend), existing glass-morphism CSS tokens.

**Key constraints:**
- 不改變現有視覺結構（hero, tabs, search, glass design tokens 保留）
- Active 不用日期分割，以最新上榜日排序，越新越前面
- Archive 依日期分組
- Columns: 代號, 名稱, 投信10日買超金額, 投信10日買超張數, 上榜日, 成長, 地雷, 便宜, 定存, 股價
- 便宜/定存暫為 placeholder（資料來源無此欄位）
- 未來資訊更新方便：新增 daily_trust10_*.json → 重跑 build_screener_history.py → 重 build Astro

---

### Task 1: Build data consolidation script

**Objective:** Create `scripts/build_screener_history.py` that reads all `daily_trust10_*.json` and produces `src/data/screener_history.json`

**Data structure:**
```json
{
  "active": [
    {
      "code": "2105", "name_zh": "正新", "name_en": "Cheng Shin...",
      "net_amount_10d": 2556344928, "net_shares_10d_zhang": 86217,
      "last_date": "2026-06-18", "cur_price": 29.65,
      "g_score": 100, "l_score": 100, "rank": 36
    }
  ],
  "archive": {
    "2026-06-18": [...],
    "2026-06-17": [...]
  }
}
```

**Logic:**
- Read all `daily_trust10_*.json` from `/root/tw-stock-monitor/output/reports/`
- Active: deduplicate by code, keep latest entry per stock, sort by `last_date` DESC (newest first)
- Archive: group all entries by date, each date sorted by `net_amount_10d` DESC
- Active defined as: appeared within last 30 days (same as existing ARCHIVE_AFTER_DAYS)

---

### Task 2: Create ScreeningTable.astro component

**Objective:** Glass-morphism table-like card component replacing the per-stock card grid

**Keep:** 
- `glass-surface` class (backdrop-filter, border, shadow)
- `::after` pseudo-element (glass sheen)
- All CSS custom properties from Layout.astro
- Hover lift effect
- Responsive breakpoints

**New layout:**
- Horizontal card (not square card) — table row style
- Columns laid out as flex/grid within the glass card
- Archive entries slightly muted (opacity)
- Score columns use color badges (green ≥80, yellow ≥60, red <60)

---

### Task 3: Update index.astro

**Objective:** Wire up new data + component

- Import `screener_history.json` instead of `stocks_summary.json`
- Active tab: render `ScreeningTable` for each active stock (flat list, already sorted)
- Archive tab: render date-grouped sections with collapsible headers
- Search still works (filter by code + name_zh)
- Tabs still work (Active/Archive toggle)
- Hero section unchanged

---

### Task 4: Build, verify, commit

- Run `python3 scripts/build_screener_history.py`
- Run `npm run build` and check for errors
- Verify output HTML has screening data
- Git commit + push
