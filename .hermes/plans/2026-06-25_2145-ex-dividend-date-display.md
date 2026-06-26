# 除息日 + 每股配息 顯示功能 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 在篩選網站的 ScreeningRow 中顯示每檔股票的「下一個除息日」和「每股配息金額」。

**Architecture:** yfinance 的 `info` dict 已經包含 `exDividendDate` (Unix timestamp) 和 `dividendRate` (年度每股配息)。只要在 `compute_value_scores.py` 的 `compute_scores()` 中多讀兩個欄位，透過 `build_screener_history.py` 寫入 JSON，再在 `ScreeningRow.astro` 加一個欄位顯示即可。不需額外 API 呼叫，不需 FinMind。

**Tech Stack:** Python (yfinance), JSON, Astro/TypeScript

---

## 已驗證的事實

yfinance 對台股回傳的 `info` 包含以下欄位（2026-06-25 實測）:

| 欄位 | 範例值 | 說明 |
|------|--------|------|
| `exDividendDate` | `1785369600` (→ 2026-07-30) | 下一次除息日的 Unix timestamp |
| `dividendRate` | `3.0` | 年度每股配息金額（新台幣） |
| `lastDividendDate` | `1785369600` | 上次除息日（若今年已除息，= exDividendDate） |

**邊界情況：** 若今年除息已過，`exDividendDate` 會指向過去的日期（如 2105 的 2026-06-17，已過）。需在前端判斷是否為未來日期，只顯示「未來」的除息日；若已過則顯示「今年已除息」或最近一次配息。

---

## Task 1: compute_value_scores.py — 新增 ex_dividend_date + dividend_per_share 到回傳值

**Objective:** 在 `compute_scores()` 函數中讀取 `exDividendDate` 和 `dividendRate`，加入回傳 dict。

**Files:**
- Modify: `scripts/compute_value_scores.py:113-277` (compute_scores function)

**Step 1: 在 compute_scores() 的 return dict 前加入除息資料**

在 `compute_value_scores.py` 第 269 行之後（`dividend_score = round(div_checks / 5 * 100, 1)` 之後），加入以下程式碼：

```python
    # ── EX-DIVIDEND DATE + PER-SHARE AMOUNT ──
    ex_div_raw = info.get("exDividendDate")
    div_rate = info.get("dividendRate")

    ex_dividend_date = None
    if ex_div_raw is not None:
        try:
            ex_dividend_date = datetime.fromtimestamp(ex_div_raw).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            ex_dividend_date = None

    dividend_per_share = round(div_rate, 2) if div_rate is not None else None
```

**Step 2: 修改 return dict，加入兩個新欄位**

將第 271-277 行的 return dict：

```python
    return {
        "cheap_score": cheap_score,
        "cheap_detail": cheap_detail,
        "dividend_score": dividend_score,
        "dividend_detail": div_detail,
        "updated_at": datetime.now().isoformat(),
    }
```

改為：

```python
    return {
        "cheap_score": cheap_score,
        "cheap_detail": cheap_detail,
        "dividend_score": dividend_score,
        "dividend_detail": div_detail,
        "ex_dividend_date": ex_dividend_date,
        "dividend_per_share": dividend_per_share,
        "updated_at": datetime.now().isoformat(),
    }
```

**Step 3: 驗證**

Run: `cd /root/stock-web-pages && python3 -c "from scripts.compute_value_scores import compute_scores; r = compute_scores('1216'); print(r.get('ex_dividend_date'), r.get('dividend_per_share'))"`
Expected: `2026-07-30 3.0` (或合理的日期/金額)

**Step 4: Commit**

```bash
cd /root/stock-web-pages
git add scripts/compute_value_scores.py
git commit -m "feat: add ex_dividend_date + dividend_per_share to value scores"
```

---

## Task 2: build_screener_history.py — 將新欄位寫入 screener_history.json

**Objective:** 在 `consolidate()` 中，把 `ex_dividend_date` 和 `dividend_per_share` 從 value_cache 寫入 active 和 archive entries。

**Files:**
- Modify: `scripts/build_screener_history.py:379-390` (active entries)
- Modify: `scripts/build_screener_history.py:431-442` (archive entries)

**Step 1: 修改 active entries 的 value scores 寫入（第 379-390 行）**

將：

```python
        # Add value scores with detail
        if code in value_cache:
            vs = value_cache[code]
            entry["cheap_score"] = vs.get("cheap_score")
            entry["cheap_detail"] = vs.get("cheap_detail")
            entry["dividend_score"] = vs.get("dividend_score")
            entry["dividend_detail"] = vs.get("dividend_detail")
        else:
            entry["cheap_score"] = None
            entry["cheap_detail"] = None
            entry["dividend_score"] = None
            entry["dividend_detail"] = None
```

改為：

```python
        # Add value scores with detail
        if code in value_cache:
            vs = value_cache[code]
            entry["cheap_score"] = vs.get("cheap_score")
            entry["cheap_detail"] = vs.get("cheap_detail")
            entry["dividend_score"] = vs.get("dividend_score")
            entry["dividend_detail"] = vs.get("dividend_detail")
            entry["ex_dividend_date"] = vs.get("ex_dividend_date")
            entry["dividend_per_share"] = vs.get("dividend_per_share")
        else:
            entry["cheap_score"] = None
            entry["cheap_detail"] = None
            entry["dividend_score"] = None
            entry["dividend_detail"] = None
            entry["ex_dividend_date"] = None
            entry["dividend_per_share"] = None
```

**Step 2: 修改 archive entries 的 value scores 寫入（第 431-442 行）**

將：

```python
        # Backfill value scores from cache (current snapshot for archive)
        if code in value_cache:
            vs = value_cache[code]
            archive_entry["cheap_score"] = vs.get("cheap_score")
            archive_entry["cheap_detail"] = vs.get("cheap_detail")
            archive_entry["dividend_score"] = vs.get("dividend_score")
            archive_entry["dividend_detail"] = vs.get("dividend_detail")
        else:
            archive_entry["cheap_score"] = None
            archive_entry["cheap_detail"] = None
            archive_entry["dividend_score"] = None
            archive_entry["dividend_detail"] = None
```

改為：

```python
        # Backfill value scores from cache (current snapshot for archive)
        if code in value_cache:
            vs = value_cache[code]
            archive_entry["cheap_score"] = vs.get("cheap_score")
            archive_entry["cheap_detail"] = vs.get("cheap_detail")
            archive_entry["dividend_score"] = vs.get("dividend_score")
            archive_entry["dividend_detail"] = vs.get("dividend_detail")
            archive_entry["ex_dividend_date"] = vs.get("ex_dividend_date")
            archive_entry["dividend_per_share"] = vs.get("dividend_per_share")
        else:
            archive_entry["cheap_score"] = None
            archive_entry["cheap_detail"] = None
            archive_entry["dividend_score"] = None
            archive_entry["dividend_detail"] = None
            archive_entry["ex_dividend_date"] = None
            archive_entry["dividend_per_share"] = None
```

**Step 3: 驗證**

Run: `cd /root/stock-web-pages && python3 scripts/build_screener_history.py 2>&1 | head -20`
然後檢查輸出 JSON: `python3 -c "import json; d=json.load(open('src/data/screener_history.json')); e=d['active'][0]; print(e.get('ex_dividend_date'), e.get('dividend_per_share'))"`
Expected: 有非 None 的日期和金額值（至少對有配息的股票）

**Step 4: Commit**

```bash
cd /root/stock-web-pages
git add scripts/build_screener_history.py
git commit -m "feat: write ex_dividend_date + dividend_per_share to screener_history.json"
```

---

## Task 3: ScreeningRow.astro — 新增除息日/配息欄位到 TypeScript interface

**Objective:** 在 `ScreeningEntry` interface 中加入 `ex_dividend_date` 和 `dividend_per_share` 可選欄位。

**Files:**
- Modify: `src/components/ScreeningRow.astro:5-25` (ScreeningEntry interface)

**Step 1: 在 interface 中加入兩個欄位**

在第 25 行（`rank: number;`）之後、`}` 之前，加入：

```typescript
  ex_dividend_date?: string | null;
  dividend_per_share?: number | null;
```

完整修改後的 interface 結尾應為：

```typescript
  cheap_score?: number | null;
  dividend_score?: number | null;
  regression_z: number;
  rank: number;
  screening_date: string;
  ex_dividend_date?: string | null;
  dividend_per_share?: number | null;
}
```

**Step 2: 同步修改 index.astro 的 interface**

在 `src/pages/index.astro` 第 29 行（`screening_date: string;`）之後，加入同樣兩行：

```typescript
  ex_dividend_date?: string | null;
  dividend_per_share?: number | null;
```

**Step 3: Commit**

```bash
cd /root/stock-web-pages
git add src/components/ScreeningRow.astro src/pages/index.astro
git commit -m "feat: add ex_dividend_date + dividend_per_share to TypeScript interfaces"
```

---

## Task 4: ScreeningRow.astro — 在 UI 中顯示除息日 + 配息金額

**Objective:** 在 ScreeningRow 的 row-center 中，Z 欄位後方新增一個除息資訊欄位。

**Files:**
- Modify: `src/components/ScreeningRow.astro:117-121` (template — Z 欄位後面插入新欄位)
- Modify: `src/components/ScreeningRow.astro:217` (CSS — 新增 .col-div 樣式)

**Step 1: 在 template 的 Z 欄位後方加入除息資訊欄位**

在第 117-120 行的 Z 欄位：

```html
    <div class="col col-z">
      <span class="col-label">Z</span>
      <span class="col-value col-muted">{entry.regression_z.toFixed(2)}</span>
    </div>
```

後面（第 121 行 `</div>` 之前，即 row-center 的結尾前）加入：

```html
    {hasValue(entry.dividend_per_share) && (
      <div class="col col-div">
        <span class="col-label">配息</span>
        <span class="col-value">{entry.dividend_per_share!.toFixed(1)} 元</span>
        {entry.ex_dividend_date && (
          <span class:list={["col-sub", { "div-future": isFutureDiv(entry.ex_dividend_date) }]}>
            除息 {formatDivDate(entry.ex_dividend_date)}
          </span>
        )}
      </div>
    )}
```

**Step 2: 在 frontmatter 區塊加入 helper 函數**

在 `ScreeningRow.astro` 的 frontmatter 中（第 51 行 `const statementUrl = ...` 之前），加入：

```typescript
function isFutureDiv(dateStr: string): boolean {
  if (!dateStr) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const divDate = new Date(dateStr);
  return divDate > today;
}

function formatDivDate(dateStr: string): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  const m = d.getMonth() + 1;
  const day = d.getDate();
  return `${m}/${day}`;
}
```

**Step 3: 加入 CSS 樣式**

在 `<style>` 區塊中，第 217 行（`.col-z { min-width: 44px; }`）後面加入：

```css
.col-div { min-width: 72px; }
.col-div .col-value {
  font-size: 0.82rem;
  font-weight: 750;
}
.col-div .div-future {
  color: var(--color-accent, #c96442);
  font-weight: 700;
}
```

**Step 4: 驗證**

Run: `cd /root/stock-web-pages && npx astro check 2>&1 | tail -5` (檢查 TypeScript 無錯誤)
然後 build: `npm run build 2>&1 | tail -10`
Expected: build 成功，無 type error

**Step 5: Commit**

```bash
cd /root/stock-web-pages
git add src/components/ScreeningRow.astro
git commit -m "feat: display ex-dividend date + per-share amount in ScreeningRow"
```

---

## Task 5: 端到端驗證 + 視覺確認

**Objective:** 確認整個管線正常運作，JSON 有資料，前端正確顯示。

**Files:** 無修改，僅驗證

**Step 1: 重新跑完整管線**

```bash
cd /root/stock-web-pages
# 清除 value scores cache 以強制重新計算
rm -f data/value_scores_cache.json
python3 scripts/build_screener_history.py 2>&1 | tail -10
```

**Step 2: 檢查 JSON 輸出**

```bash
python3 -c "
import json
d = json.load(open('src/data/screener_history.json'))
for e in d['active'][:5]:
    print(f\"{e['code']} {e.get('name_zh','')}: ex_div={e.get('ex_dividend_date')}, per_share={e.get('dividend_per_share')}\")
"
```

Expected: 至少部分股票顯示非 null 的 ex_dividend_date 和 dividend_per_share

**Step 3: Build 網站**

```bash
cd /root/stock-web-pages
npm run build 2>&1 | tail -10
```

Expected: build 成功

**Step 4: 檢查 build 產出**

```bash
ls -la dist/ 2>/dev/null || ls -la ./dist/ 2>/dev/null
```

**Step 5: Commit all**

```bash
cd /root/stock-web-pages
git add -A
git commit -m "chore: rebuild screener_history with ex-dividend data" --allow-empty
```

---

## 修改摘要

| 檔案 | 行號 | 改動 |
|------|------|------|
| `scripts/compute_value_scores.py` | 269-277 | 新增 ex_dividend_date + dividend_per_share 到 compute_scores() 回傳值 |
| `scripts/build_screener_history.py` | 379-390 | active entries 加入兩個新欄位 |
| `scripts/build_screener_history.py` | 431-442 | archive entries 加入兩個新欄位 |
| `src/components/ScreeningRow.astro` | 5-25 | ScreeningEntry interface 加兩個可選欄位 |
| `src/components/ScreeningRow.astro` | ~51 | 新增 isFutureDiv() + formatDivDate() helper |
| `src/components/ScreeningRow.astro` | 117-121 | Z 欄位後插入除息資訊欄位 |
| `src/components/ScreeningRow.astro` | ~217 | 新增 .col-div CSS |
| `src/pages/index.astro` | 29 | ScreeningEntry interface 同步加兩個欄位 |

**總改動：~40 行新增代碼，0 行刪除，跨 4 個檔案。**

## 設計決策

1. **不需要 FinMind**：yfinance 的 `info` dict 已包含 `exDividendDate` 和 `dividendRate`，已在 `compute_scores()` 中透過 `tk.info` 取得，不需額外 API 呼叫。
2. **過去的除息日處理**：若 `exDividendDate` 已過（今年已除息），前端仍顯示日期但用灰色而非 accent 色。不做「預測下次除息日」的推算（YAGNI）。
3. **null 安全**：所有新欄位都是 optional（`?: string | null`），不會破壞既有資料。
4. **快取相容**：`value_scores_cache.json` 舊格式不含新欄位時，`get_scores()` 回傳的 dict 會缺少 key，`vs.get("ex_dividend_date")` 回傳 None，安全降級。
