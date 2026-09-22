# 總報酬估值命名與一年篩選歷史 Implementation Plan

> **For Hermes:** 執行時使用 `subagent-driven-development`，先完成 plan QA certification，再按 task 串行／並行執行；本文件本輪只規劃，不執行。

**Goal:** 把成長股 UI 改成清楚的總報酬估值方法命名，並在不使用資料庫的前提下，讓使用者查詢最近一年每個交易日的三策略篩選紀錄。

**Architecture:** 保留目前 React/Vite + Cloudflare Pages 的純靜態架構。每日 GitHub Actions 產生一份小型、版本化的篩選歷史 archive；前端依日期／策略載入 archive，不讀取一年份的完整 53MB 個股 release。`latest.json` 與當日完整 detail 仍是目前 dashboard 的即時資料；歷史頁只顯示當日篩選結果與可追溯 metadata。

**Tech Stack:** React 19、TypeScript、Vite、Vitest、Python 3.12、pytest、GitHub Actions、Cloudflare Pages。無 DB、無 API server、無 R2。

---

## 0. 已知現況與產品決策

已確認基線：

- production/main：`135c6c5`
- `latest.json` 約 4.9MB。
- 一份完整 release 約 52.8MB；目前已有 24 個 release directory。若一年保存約 250 個完整 release，約 12.3 GiB，不能直接把完整 detail 當歷史查詢資料。
- 現有資料路徑：`public/data/latest.json`、`public/data/releases/<runId>/stocks/*.json`。
- 每日 workflow：`.github/workflows/daily.yml`，Asia/Taipei 18:00 cron 觸發 workflow_dispatch。
- 原始老師影片字幕目前不可取得；產品文案不得暗示老師本人審核、授權或背書。

### P0 UI 命名

所有網頁上的：

- `影片版總報酬本益比`
- `影片版情境合理價`
- `低估參考價`

改成：

- `總報酬本益比（本站整理）`
- `總報酬估值參考價（本站整理）`
- `低估門檻參考價（本站整理）`

旁邊提供 `ⓘ` tooltip：

> 本站依公開方法與現有研究文件整理實作；數值是研究參考，不是目標價、買賣建議或即時報價。

`aria-label`：

> 說明總報酬本益比的計算方法與資料限制

保留方法版本 `growth-total-return-pe-v1`，不要把方法版本藏掉。

---

## 1. Plan QA gate：先審 plan，不准直接改碼

### 並行 dispatch 3 個只讀 subagent

每個 worker 都收到本 plan 絕對路徑、目前 commit、`只讀／不可修改／不可 commit／不可 push／不可 deploy` 限制，並回傳：

```json
{
  "verdict": "CERTIFIED|REVISE",
  "blocking_issues": [],
  "answer_key_gaps": [],
  "evidence_checked": [],
  "summary": ""
}
```

- **QA-PLAN-DATA**：檢查 archive schema、hash、revision、366 日保留、交易日／休市語意、fail-closed。
- **QA-PLAN-UX**：檢查總報酬估值命名、非背書聲明、日期／策略／股票查詢 UX、ARIA、手機版。
- **QA-PLAN-OPS**：檢查 GitHub Actions、Cloudflare cache、git repo 成長、失敗時不更新 latest、rollback、secret safety。

任何一個 `REVISE` 都停止 execution；修改本 plan 後重新審查。3 個 reviewer 全部 `CERTIFIED` 才能進入 Task 2。

---

## 2. Static history data contract

### 建議檔案

建立：

- `pipeline/history_archive.py`
- `pipeline/test_history_archive.py`
- `scripts/build_history_archive.py`
- `scripts/verify_history_archive.py`
- `public/data/archive/v1/index.json`
- `public/data/archive/v1/months/YYYY-MM.<sha12>.json`
- `public/data/schemas/screening-history-v1.schema.json`

### Exact JSON contract

`index.json` 必須符合：

```json
{
  "schemaVersion": "screening-history-index-v1",
  "generatedAt": "ISO-8601",
  "retentionDays": 366,
  "earliestMarketDate": "YYYY-MM-DD|null",
  "latestMarketDate": "YYYY-MM-DD|null",
  "months": [
    {
      "month": "YYYY-MM",
      "path": "/data/archive/v1/months/YYYY-MM.<sha12>.json",
      "sha256": "64 lowercase hex",
      "bytes": 1234,
      "marketDateStart": "YYYY-MM-DD",
      "marketDateEnd": "YYYY-MM-DD",
      "recordCount": 20
    }
  ]
}
```

每個月份檔必須符合：

```json
{
  "schemaVersion": "screening-history-month-v1",
  "month": "YYYY-MM",
  "records": [
    {
      "marketDate": "YYYY-MM-DD",
      "generatedAt": "ISO-8601",
      "runId": "non-empty string",
      "revision": "12 lowercase hex",
      "freshness": "current|stale|degraded",
      "statusMessage": "string",
      "formulaVersions": {
        "regression": "string",
        "valuation": "string",
        "growthValuation": "string",
        "growthFallback": "string",
        "ranking": "string"
      },
      "funnel": {
        "universe": 0,
        "priceComplete": 0,
        "valuationComplete": 0,
        "growthValuationComplete": 0,
        "pegCandidates": 0,
        "growthCandidates": 0,
        "strategyCandidates": {"trust": 0, "growth": 0, "lowPosition": 0},
        "formalValuations": 0,
        "proxyValuations": 0
      },
      "strategies": {
        "trust": ["compact row"],
        "growth": ["compact row"],
        "lowPosition": ["compact row"]
      },
      "sourceRefs": ["string"]
    }
  ]
}
```

compact row 的 schema 設定 `additionalProperties=false`。required fields 是 `rank:int>=1`, `code:^[0-9A-Z-]+$`, `name:string`, `sector:string`, `value:number|null`, `valueLabel:string`, `status:pass|fail|unknown|not_applicable`, `reason:string`；可選欄位只允許 `entryStatus:new|retained|unknown|not_applicable`, `sourceRank:int|null`, `previousRank:int|null`, `currentPrice:number|null`, `currentPeg:number|null`, `growthTotalReturnPe:number|null`, `growthFairPrice:number|null`, `growthBuyZonePrice:number|null`, `valuationEvidenceLevel:formal|proxy|unavailable`, `valuationFormulaVersion:string`。所有日期必須是 ISO `YYYY-MM-DD`，所有 JSON object 都 `additionalProperties=false`，不可有未列出的大型欄位。

Hash／revision 規則固定如下：

- canonical JSON：Python `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))`。
- 編碼：UTF-8、無 BOM、無 trailing newline。
- `sha256` 是月份檔 canonical UTF-8 bytes 的完整 SHA-256；index 不 hash 自己。
- `revision` 是「移除 `revision` 欄位後」daily record canonical bytes 的 SHA-256 前 12 碼；驗證時先刪掉 revision 再重算，避免 self-reference。
- 月份檔名使用 `YYYY-MM.<sha12>.json`，其中 `<sha12>` 必須等於該月份 canonical bytes SHA-256 的前 12 碼；verifier 與 test 都必須檢查 filename suffix、index `sha256`、實際 bytes 三者一致。
- index 的 `bytes` 是月份檔實際 UTF-8 byte size。

Atomic publish 規則：

1. builder 只寫 `.history-staging/<random-id>/archive/v1/`，不先刪 production archive。
2. 完整寫入所有 hashed month files、index、schema validation 後，先跑 verifier。
3. verifier PASS 後，先以 `os.replace` 安裝新增 immutable month files，再最後以單次 `os.replace(index.tmp, index.json)` 更新 mutable pointer；index 只會指向已存在且已驗證的檔案。中斷時舊 index 仍完整可用，未被 pointer 引用的 hashed files 可安全清理。
4. 任何 cleanup 都在新 index 安裝成功後才做；cleanup 失敗不得回刪目前 pointer。
5. GitHub Actions 只有所有 tests PASS 才 commit/push，因此任何 archive failure 都不會更新 `latest.json` 或 production pointer。
6. 有可用但過期的 baseline release（`freshness=stale|degraded` 且有 `marketDate`）可以建立 stale history record，UI 必須照實標示；真正缺少 baseline、缺 `marketDate` 或 `freshness=unavailable` 直接 BLOCKED，不建立 record。

歷史 archive 使用「月份分片」，不是一年 250 個 request：

- `index.json`：約 12 個月份 metadata、最早／最新交易日、retention、schema、hash。
- `months/YYYY-MM.<sha12>.json`：該月每日 compact 篩選紀錄。
- 每筆 daily record：
  - `marketDate`
  - `generatedAt`
  - `runId`
  - `revision`
  - `formulaVersions`
  - `funnel`
  - `strategies.trust`
  - `strategies.growth`
  - `strategies.lowPosition`
  - `sourceRefs`
- ranking row 只保留：
  - code、name、sector、rank
  - value、valueLabel、status、reason
  - entryStatus／sourceRank／previousRank
  - currentPrice、currentPeg
  - `growthTotalReturnPe`
  - `growthFairPrice`
  - `growthBuyZonePrice`
  - valuation evidence／formula version
- 不放：
  - `priceSeries`
  - 原始財報 rows
  - `financialInputs`
  - 完整 chip raw data
  - 大型 regression history

同一 `marketDate` 重跑：

1. 產生新 `revision`／新 hash。
2. 替換月份內該日期的 pointer。
3. 舊檔最多保留上一版，未被 index 引用的舊版本可刪。
4. 不允許同一月份出現兩筆相同日期。

保留規則：

- 保留最近 366 個日曆日內的交易日紀錄。
- 非交易日不建立空紀錄。
- 沒有 `marketDate`、schema 不完整、hash 不符時，整次 archive build fail closed。
- 一年 archive raw bytes 目標 `< 20 MB`；單月超過 `2 MB` 時 QA fail，避免把完整 detail 偷塞進歷史檔。

---

## 3. Data implementation

### Task 3.1：先寫 failing contract tests

**Files**

- Create: `pipeline/test_history_archive.py`
- Create: `scripts/test_verify_history_archive.py`
- Create: `scripts/verify_neutral_copy.py`
- Create: `scripts/test_verify_neutral_copy.py`
- Create: `scripts/verify_history_production.py`

測試：

- compact projection 不包含大型欄位。
- 日期排序正確。
- 同日期 rerun 只留下最新 revision。
- 休市／`marketDate=null` 不新增紀錄。
- 366 日裁切。
- 錯誤 hash、filename suffix mismatch、錯誤 schema 皆 fail。
- 模擬 final index `os.replace` 前中斷：舊 index bytes／hash 保持不變，新增未引用 month file 不被當成有效 pointer。
- 舊月份不會意外刪掉 retention 內資料。
- archive build 失敗時不宣稱成功。

Run:

```bash
pytest pipeline/test_history_archive.py scripts/test_verify_history_archive.py -q
```

Expected first run：FAIL，因 archive module 尚未存在。

### Task 3.2：實作 archive builder

**Files**

- `pipeline/history_archive.py`
- `scripts/build_history_archive.py`

實作：

- `project_release_to_history(release) -> DailyHistoryRecord`
- `merge_month(existing, record)`
- `prune_to_retention(months, today, 366)`
- `write_archive_atomic(staging_dir, archive_dir)`
- SHA-256 canonical JSON hash。
- deterministic ordering，避免每日相同資料造成無意義 diff。
- `--data-dir`、`--as-of`、`--retention-days`、`--check-only` flags。
- 所有輸入欄位 allowlist；未知欄位不可整包複製進 archive。

### Task 3.3：實作 archive verifier

**Files**

- `scripts/verify_history_archive.py`
- `public/data/schemas/screening-history-v1.schema.json`
- `scripts/verify_snapshot.py`（只增加 archive pointer／version 檢查，不重複 parser）

檢查：

- index／month schema。
- index hash 等於實際 month bytes。
- month 日期唯一、排序、都在 retention。
- latest 的當日 record 與 archive pointer 一致。
- strategies 與 funnel 數量守恆。
- archive size budget。
- `runId`、formula version、marketDate 可追溯。

---

## 4. Daily workflow integration

**Create**

- `scripts/prune_releases.py`
- `scripts/test_prune_releases.py`

**Modify**

- `.github/workflows/daily.yml`
- `public/_headers`
- `README.md`

Static release retention policy:

- Keep the current `latest.json` run plus at most two previous full release directories.
- Never delete the run referenced by `latest.json`; never delete archive files through this command.
- `scripts/prune_releases.py` fails if the current run is missing, a path escapes `public/data/releases`, or after pruning `public/data` exceeds 250 MB.
- This controls working tree／Pages size; it does not pretend to shrink old Git blobs. A separate repository compaction decision remains out of scope.

Workflow 順序：

1. fetch source。
2. refresh `latest.json`／完整 release 到 staging。
3. `python scripts/verify_snapshot.py`。
4. `python scripts/build_history_archive.py`。
5. `python scripts/verify_history_archive.py`。
6. `python scripts/prune_releases.py --data-dir public/data --keep 3 --max-bytes 250000000`。
7. `python scripts/verify_snapshot.py`（prune 後再驗證 current run）。
8. `python scripts/verify_neutral_copy.py --paths src public/data`。
9. pytest、typecheck、build。
10. 所有 gate PASS 才 `git add public/data`、commit、push。
11. 任一 gate 失敗：不 push，不更新 production pointer。

`public/_headers`：

```text
/data/archive/v1/index.json
  Cache-Control: no-cache, no-store, must-revalidate
/data/archive/v1/months/*
  Cache-Control: public, max-age=31536000, immutable
```

說明：

- index 是 mutable pointer，必須 revalidate。
- 月份檔依 content hash／revision 更新；不可讓 CDN 永久吃舊 pointer。
- 不把完整舊 release 再複製到 archive。

新增 workflow fixture：

- archive build failure → no git push。
- hash mismatch → no git push。
- duplicate market date → no git push。
- valid stale/offline baseline → archive 顯示 stale/degraded metadata，不冒充 current；missing baseline／missing marketDate／unavailable → BLOCKED、no archive pointer update。

---

## 5. Frontend history feature

### Task 5.1：types、API、純函式

**Files**

- `src/domain/types.ts`
- `src/data/api.ts`
- Create: `src/domain/history.ts`
- Create: `src/domain/history.test.ts`

新增：

- `ScreeningHistoryIndex`
- `ScreeningHistoryMonth`
- `ScreeningHistoryRecord`
- `HistoryRankingRow`
- `loadHistoryIndex()`
- `loadHistoryMonth(month)`
- schema validation、hash metadata validation。
- `sessionStorage` cache；不使用 DB、不把一年資料寫入 localStorage。
- month request dedupe：同月份只 fetch 一次。
- archive unavailable 時顯示「歷史資料同步中／暫不可用」，不讓整個 dashboard crash。

URL state：

```text
?view=history
&strategy=growth
&from=2025-09-22
&to=2026-09-22
&code=2382
```

Query semantics are fixed:

- `from` and `to` are inclusive `YYYY-MM-DD`, interpreted in Asia/Taipei market-date semantics.
- Default is the latest 30 available market dates from the index, not 30 calendar days.
- Non-trading dates are valid inputs but show zero records and an explicit「休市／沒有發布」state; no silent date shifting.
- `from > to` shows validation error and performs no month fetch.
- Dates outside retention are clamped to index bounds with a visible「已限制在可查詢期間」notice。
- `strategy` accepts only `all|trust|growth|lowPosition`; unknown values normalize to `all`。
- `code` trims whitespace, converts full-width digits to ASCII, and performs prefix match on code or case-insensitive substring match on name. Empty means no stock filter.
- 初次載入解析 query 後只做一次 canonicalize；使用者 filter 改變才用 `replaceState`。`popstate` 只更新 React state，不再次寫 URL，禁止 popstate→replaceState loop。未知 query keys 忽略；back/forward 必須還原對應 filter。
- Date inputs are real focusable controls with `aria-invalid` and an associated error text。

### Task 5.2：History UI

**Files**

- Create: `src/components/HistoryPanel.tsx`
- Create: `src/components/HistoryPanel.test.tsx`
- `src/App.tsx`
- `src/components/StrategyCard.tsx`
- `src/domain/strategyPresentation.ts`
- `src/styles.css`
- `src/domain/events.ts`

UI：

- Header 增加「歷史篩選」按鈕。
- 預設：最近 30 個交易日；不是一進頁就下載一年。
- 可選：
  - 起始日／結束日
  - 策略：全部／投信新進榜／成長股／低位觀察
  - 股票代號／名稱
- 日期結果以日期卡片或表格顯示：
  - 資料日
  - 當日策略數
  - candidate rows
  - 新進榜／續留／資料未知狀態
  - runId 與 formula version
- `growth` 所有文案使用：
  - `總報酬本益比（本站整理）`
  - `總報酬估值參考價（本站整理）`
  - `低估門檻參考價（本站整理）`
- 方法說明使用可聚焦 `<button>`，有 `aria-expanded`、`aria-controls`，按 Enter／Space 開關；tooltip 文字不依賴 hover。
- 日期 input：
  - `aria-label="選擇歷史起始交易日"`
  - `aria-label="選擇歷史結束交易日"`
  - `aria-describedby` 指向錯誤／限制說明。
- Filter 變更同步 URL；貼 URL、重新整理、back/forward 可重現相同查詢。
- 鍵盤 Tab、Enter、Space、Arrow、Home、End、Escape 可操作。
- 股票搜尋空值顯示全部；無結果顯示結果數 0 與清除按鈕。
- 所有 production-facing text scope（`src/` 全樹、`public/data/latest.json`、current release 的 ranking reason／valuation reason、`public/data/archive/v1`、以及部署進入 bundle 的文案）不得再出現 `影片版`、`video`、`teacher`、`陳喬泓`、`老師` 或其他個人歸屬字樣；方法只用中性「總報酬本益比（本站整理）」與「總報酬估值參考價」。
- 建立 `scripts/verify_neutral_copy.py`，掃描上述 production-facing paths；source URL 本身只檢查渲染文字，不把合法 provider hostname 當文案。任何 forbidden term 直接 nonzero，daily workflow 在 commit 前執行。
- 手機版不出現橫向溢位。

---

## 6. Subagent execution design

### 可並行

在 schema contract 與 plan QA `CERTIFIED` 後：

- **Data worker**：Task 3 + 4，獨立 worktree，嚴格 TDD；不得改 UI。
- **Frontend worker**：Task 5，依已凍結 schema，獨立 worktree；不得改 workflow。
- **UX/accessibility worker**：讀取 UI diff，提供文案／ARIA 建議，不改 data contract。

### 必須串行

1. Parent 完成 contract／plan QA。
2. Data worker 完成 archive + verifier。
3. Parent 驗證 data worker tests，凍結 JSON fixture。
4. Frontend worker 依 fixture 實作 UI。
5. Integration worker 合併兩邊並跑全套 tests。
6. **QA worker** 獨立檢查，不與 implementation worker 共用判定。
7. Release worker 只在 QA PASS 後執行 candidate SHA、commit、push、deploy、live verify。

每個 implementation subagent 必須回傳：

- 修改檔案清單。
- failing test → passing test 證據。
- test command／exit code。
- commit SHA。
- 未完成事項。
- 不得輸出 secret、prompt、token。

---

## 7. QA plan

### Automated QA

```bash
pytest pipeline scripts -q
python scripts/verify_snapshot.py
python scripts/verify_history_archive.py
npm run test:unit
npm run typecheck
npm run build
git diff --check
```

### Browser／dogfood QA

QA subagent 使用 live preview：

1. Dashboard 初始載入。
2. 點「歷史篩選」。
3. 選 growth。
4. 選起訖交易日。
5. 搜尋 `2382`。
6. 確認 query URL 可重現。
7. 確認總報酬估值文案與 tooltip。
8. 確認沒有任何影片／video／teacher／個人冠名文字。
9. 失敗載入 index／month 時顯示可理解錯誤。
10. 桌機、手機寬度、鍵盤操作。
11. Network：index no-cache、month immutable。
12. console 無未捕捉錯誤。

若 browser harness 啟動失敗，不得宣稱 DOM QA PASS；改報 `BLOCKED`，以 Vitest、HTTP、bundle、headers smoke 補足。

---

## 8. answer.key（執行前先寫入 QA 證據）

| QA ID | Objective PASS condition | Evidence |
|---|---|---|
| QA-01 | `src/`、latest、current release、archive 的 rendered/user-facing fields 不含影片／video／teacher／個人冠名字樣；中性總報酬文案存在 | `verify_neutral_copy.py` + frontend tests |
| QA-02 | index／month schema、hash、filename suffix、日期唯一、366 日 retention 全通過 | `verify_history_archive.py` JSON result |
| QA-03 | final index replace 中斷時舊 index unchanged、未引用 hashed file 不可被 UI 讀取 | atomic interruption fixture |
| QA-04 | 同日期 rerun idempotent；latest pointer 只指向一個 revision | pytest fixture |
| QA-05 | 一年 archive raw size < 20MB、單月 < 2MB | archive size report |
| QA-06 | 休市、缺日、source timeout、hash mismatch fail closed | negative fixtures + nonzero exit |
| QA-07 | inclusive date、最近 30 交易日 default、休市、retention 外日期、from>to 都有明確 expected state | `history.test.ts` fixtures |
| QA-08 | strategy all/trust/growth/lowPosition、代號 prefix、名稱 substring、空值／無結果正確 | `HistoryPanel.test.tsx` |
| QA-09 | 初載入 canonicalize、filter replaceState、popstate 不寫 URL 且可還原 | URL state unit test |
| QA-10 | keyboard／ARIA／mobile smoke PASS | frontend QA report |
| QA-11 | daily workflow archive gate 失敗時不 push；dry-run fixture 檢查 git HEAD／remote ref 未變 | publish guard test + run log |
| QA-12 | candidate commit SHA 建立後 fresh worktree 重跑全部 gates，push 的 SHA 等於測試 SHA | exact SHA evidence |
| QA-13 | production latest/index/month 對 candidate expected-dir allowlist 逐欄一致，且 index/month cache headers 正確 | `verify_history_production.py` JSON result |
| QA-14 | neutral-copy scanner 對 source、latest、current release、archive 全部 PASS | `verify_neutral_copy.py` JSON result |
| QA-15 | full release retention <= 3、`public/data` <= 250MB，且 current run 不被刪 | `prune_releases.py` JSON result |
| QA-16 | rollback 使用已記錄 previous git SHA／Pages deployment，重部署後 production pointer 可驗證回復 | rollback rehearsal evidence |

每筆 QA 結果格式：

```json
{
  "qa_id": "QA-01",
  "status": "PASS|FAIL|BLOCKED|N/A",
  "evidence": "/absolute/path/under/evidence-bundle",
  "command": "redacted command summary",
  "observed": "factual result",
  "negative_proof": "what did not happen",
  "remaining_prerequisite": ""
}
```

---

## 9. Release、feature flag、rollback

### Candidate SHA 與 rollback evidence

1. 先在乾淨 candidate worktree 執行所有 tests，記錄 tree SHA。
2. commit code + generated archive；記錄 candidate commit SHA。
3. 從該 exact commit 建立 fresh worktree，再跑完整 gates；不同 SHA 直接 BLOCKED。
4. push exact candidate SHA；用 `git ls-remote origin refs/heads/main` 驗證。
5. deploy 後記錄 Pages deployment URL／deployment id、git SHA、archive index hash。
6. rollback 使用記錄的 previous commit SHA 或 previous Pages deployment artifact；重新 deploy 後再次跑 QA-13，不以「部署成功」banner 當 rollback 成功。

Production smoke command：

```bash
python scripts/verify_history_production.py \
  --base-url https://stockscreener.andyshih.uk \
  --expected-dir public/data
```

Verifier 必須用 exact candidate `public/data` 作 expected source，執行：

- GET `/data/latest.json?cachebust=<candidate-sha>`、`/data/archive/v1/index.json?cachebust=<candidate-sha>`，均 HTTP 200。
由 local index 取 exact hashed month path，再 GET 該 path 加 `?cachebust=<candidate-sha>`，避免誤讀 CDN 舊回應。
- field-level compare：latest 的 schema／strategy／formula／marketDate／runId／generatedAt／freshness／statusMessage／sourceRefs／funnel／三策略 compact projection；index 的 schema／retention／date bounds／month path／sha256／bytes／recordCount；month 的 hash／filename suffix／month／records／latest revision。三份 JSON 都必須套用同一份 `additionalProperties=false` schema；遇到未列出的 top-level 或 nested field 直接 nonzero。
- verify response headers：index 包含 `no-cache`、`no-store`、`must-revalidate`；hashed month 包含 `public`、`immutable` 且 `max-age >= 31536000`。
- 任一 mismatch、缺 header、非 200 都 nonzero。

Rollback rehearsal：

```bash
set -euo pipefail
PREVIOUS_SHA="$(git rev-parse origin/main^)"
test -n "$PREVIOUS_SHA"
ROLLBACK_DIR="/tmp/stock-web-rollback-$PREVIOUS_SHA"
git worktree add "$ROLLBACK_DIR" "$PREVIOUS_SHA"
(
  cd "$ROLLBACK_DIR"
  npm ci
  npm run build
  python scripts/verify_snapshot.py
  npx wrangler@latest pages deploy "$ROLLBACK_DIR/dist" --project-name stock-web-pages --branch main
  python scripts/verify_history_production.py \
    --base-url https://stockscreener.andyshih.uk \
    --expected-dir "$ROLLBACK_DIR/public/data"
)
```

### Shadow phase

- 先產生 archive 5 個交易日，但 UI feature flag 關閉。
- 每日 workflow 照常驗證 archive；不改既有 dashboard。
- 5 日後 QA 檢查 archive size、missing date、CDN headers、query latency。

### Enable

- `VITE_HISTORY_ENABLED=true` 才顯示「歷史篩選」按鈕。
- archive index 缺失時即使 flag 開啟，也只顯示同步中狀態。

### Rollback

- UI bug：將 `VITE_HISTORY_ENABLED=false`，重新 build/deploy。
- Archive data bug：回復 `index.json` 到前一個 validated commit；不要刪除上一版 immutable month。
- code bug：revert feature commit，fresh CI、snapshot verifier、build 後再 deploy。
- 不使用資料庫 migration，因此沒有 schema rollback migration。
- 不把完整舊 release 重新暴露給歷史 UI。

---

## 10. 不做與風險

不做：

- 不建立 DB。
- 不新增 API server。
- 不使用 R2／外部付費 storage。
- 不把一年完整 priceSeries／財報／chip raw 放進 archive。
- 不做回測或把歷史篩選紀錄描述成績效。
- 不替任何個人或老師冠名、背書或暗示授權。
- 不在本 feature 中改變 `growth-total-return-pe-v1` 公式。

風險：

- Git 歷史舊 blobs 不會因刪目錄自動縮小；P1 需另外評估 repo archive／release retention。
- 同一交易日重跑可能產生 revision；index 必須明確指向最新 validated revision。
- Cloudflare cache 若 index 沒 no-cache，使用者可能看到舊月份 pointer。
- 休市日與資料延遲不可當作零候選；必須顯示缺日／stale。
- 方法來源文字必須永遠搭配「本站整理、非目標價／投資建議」。

**本 plan 完成後才進入 execution；本輪不改 repo、不提交、不部署。**
