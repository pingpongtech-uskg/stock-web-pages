# 三策略籌碼參考資訊 Implementation Plan

> **For Hermes:** 執行時使用 `subagent-driven-development`，逐任務完成；所有 subagent 從 `default` profile 啟動，繼承 default model。不得切換 `product-manager` profile，不得自行加入 critic／外部審查流程。

**Goal:** 將「大股東持股、董監持股、總股東人數」做成三個策略共用的籌碼參考資訊；只展示，不參與三個策略的母體、排序、候選資格、漏斗或進榜條件。

**Architecture:** 後端每日發布靜態快照。股權資料以月／週來源正規化為 `ownershipMonthly`，由獨立 evaluator 產生三個 `chipReference` 指標。前端在投信關注、成長改善、低位觀察三個 tab 的股票列顯示同一份參考摘要；資料缺漏顯示 `unknown／待補資料`，不刪除股票、不改策略結果。

**Tech Stack:** Python pipeline、JSON release contract、React/TypeScript、Vitest、pytest、GitHub Actions、Cloudflare Pages。

**Baseline:** `/tmp/stock-web-deploy`，branch `resume-strategy`，HEAD `c8b5c08780d40754292c337b9dda39edc6c71c33`。目前 worktree 已確認乾淨。

---

## 1. Product decision

### 1.1 In scope

- 每檔股票新增三個參考指標：
  1. 大股東持股比重連續三個月上升。
  2. 董監持股最新值較 12 個月前持平或上升。
  3. 總股東人數連續三個月下降。
- 三個策略 tab 都顯示同一份 `chipReference`。
- 顯示每項：目前值、比較期間、趨勢結果、來源、資料日、公式版本、資料新鮮度。
- `pass／fail／unknown` 只描述參考指標，不代表買進、策略通過或候選資格。

### 1.2 Explicit non-goals

- 不把籌碼參考加入 `trust`、`growth`、`lowPosition` 策略 gate。
- 不改 A 母體、Top10、PEG、Z 值、slope、strategy candidate count、funnel count。
- 不用投信十日淨買超代理大股東持股。
- 不用投信賣超代理總股東人數下降。
- 不抓財報狗頁面，也不宣稱複製財報狗／StatementDog 內部算法。
- 不因股權資料抓取失敗而把整個 release 標成資料不可用；只標記 `chipReference` 自己的 freshness/status。

### 1.3 Product wording

主畫面固定標示：

> **籌碼參考（不影響策略篩選）**

方法頁補充：

> 三項趨勢只作研究參考，不構成買進訊號。缺少完整月份、來源未發布或來源欄位意義不明時，顯示未知，不以代理值補通過。

---

## 2. Current-state findings

目前程式已有三個同名欄位，但不能直接沿用：

- `pipeline/health_checks.py:30-34` 已定義 `chip` 三項規則。
- `pipeline/health_checks.py:277-283` 實際用投信十日淨買賣超做代理；這不是正式股權資料。
- `docs/HEALTH_CHECKS.md:14,27-42` 已規劃 `ownership_monthly`、MOPS／TDCC，但尚未接入正式歷史資料。
- `config/source_registry.json` 已將 TDCC 列入官方 allowlist；來源探針與欄位 evidence 見 `docs/source-evidence/`。
- `src/domain/types.ts` 已有 `HealthCategory`／`RuleCheck`，但沒有獨立 `chipReference` 型別。
- `src/components/StrategyCard.tsx` 現在只渲染策略 row；參考資訊應以獨立區塊加入，不能讓 `isRenderableRow()` 讀取籌碼狀態。

現有投信代理必須移除或改為 compatibility-only unknown；不得繼續對外顯示成正式籌碼判定。

---

## 3. Canonical data contract

### 3.1 Normalized ownership input

新增 `pipeline/ownership_inputs.py`，正規化後每筆資料至少包含：

```json
{
  "code": "2330",
  "market": "TWSE",
  "period": "2026-08",
  "asOf": "2026-08-28",
  "publishedAt": "2026-09-04",
  "retrievedAt": "2026-09-21T00:00:00+08:00",
  "largeHolderPct": 42.8,
  "directorSupervisorPct": 18.3,
  "shareholderCount": 12540,
  "source": "TDCC/MOPS",
  "dataset": "<approved dataset id>",
  "snapshotId": "<immutable source snapshot id>",
  "schemaVersion": "ownership-v1"
}
```

欄位規則：

- `largeHolderPct`、`directorSupervisorPct` 單位固定 `%`；不得把百分比小數與百分點混用。
- `shareholderCount` 單位固定 `人`。
- 缺值為 `null`，不能填 0。
- 每筆保存 `asOf`、`publishedAt`、`retrievedAt`、source、dataset、snapshotId。
- 只使用不晚於 release `marketDate` 可取得的資料，禁止 look-ahead。
- raw source payload 存在受控 evidence/cache 目錄，不進 `dist/`；公開 release 只放必要正規化結果與來源 metadata。

### 3.2 Reference result

新增 `chipReference`：

```json
{
  "schemaVersion": "chip-reference-v1",
  "status": "pass|fail|unknown",
  "displayOnly": true,
  "formulaVersion": "chip-reference-v1",
  "dataFreshness": "current|stale|unavailable",
  "largeHolderTrend": {
    "status": "pass|fail|unknown",
    "value": "42.1% → 42.5% → 42.8%",
    "period": "2026-06..2026-08",
    "rawValues": [42.1, 42.5, 42.8],
    "sourceRefs": []
  },
  "directorSupervisor12m": {
    "status": "pass|fail|unknown",
    "value": "18.3% vs 17.9%",
    "period": "2026-08 vs 2025-08",
    "rawValues": {"latest": 18.3, "prior12m": 17.9},
    "sourceRefs": []
  },
  "shareholderCountTrend": {
    "status": "pass|fail|unknown",
    "value": "12,900 → 12,670 → 12,540",
    "period": "2026-06..2026-08",
    "rawValues": [12900, 12670, 12540],
    "sourceRefs": []
  },
  "sourceRefs": [],
  "availableAt": "2026-09-04"
}
```

判定：

```text
largeHolderTrend:       v[-3] < v[-2] < v[-1]
directorSupervisor12m:  latest >= value_12_months_ago
shareholderCountTrend:  v[-3] > v[-2] > v[-1]
```

- 三個月條件採嚴格連續上升／下降。
- 董監持股採持平或上升。
- 少於三個有效月份、缺少 12 個月對照、月份不連續、來源定義不明 → `unknown`。
- 不以較短期間代替完整期間。
- `chipReference.status` 可作摘要，但任何策略程式不得讀取它作篩選條件。

### 3.3 Definition freeze — blocker resolved for implementation review

來源探針已完成，證據存於 `docs/source-evidence/chip-reference-official-sources-2026-09-21.md`。不再把「找不到資料」列為 blocker；只保留透明定義，避免宣稱複製 StatementDog 未公開算法：

- `largeHolderPct`：TDCC `1-5` 的 `持股分級=15` `占集保庫存數比例%`；官方查詢頁定義級距15為「1,000,001以上」。級距16是「差異數調整（說明4）」不納入持股比重。UI 名稱用 `TDCC 高持股級距15（持股1,000,001以上）`。
- `shareholderCount`：TDCC `1-5` 的 `持股分級=17` `人數`；以官方總計列為準，不自行把分級人數相加。
- TDCC 資料取每個曆月最後一筆已發布週資料；三個月必須是三個有效月份。
- `directorSupervisorPct`：TWSE OpenAPI `t187ap11_L/P`；加總職稱為 `董事長本人`、`董事本人`、`獨立董事本人`、`監察人本人` 的 `目前持股`，除以同月官方已發行普通股數。
- 12 個月比較使用相同職稱範圍與資料年月；月份或分母不一致 → `unknown`。
- 公司分割、增資、減資或分母無法對齊 → `unknown`，不自行調整成通過。

這是我們自己的公開資料參考定義，不是 StatementDog exact clone。Oma double-check 通過後，才進入 evaluator／release／UI implementation；本階段不改策略邏輯。

---

## 4. Data acquisition plan

### 4.1 Preferred source path

| 指標 | 首選 | 目的 | 必須保存 |
|---|---|---|---|
| 大股東持股比重 | TDCC 股權分散資料 | 取得指定大戶級距持股比重 | 級距、分母、期別、發布日 |
| 董監持股 | TWSE OpenAPI `t187ap11_L/P` | 取得最新與 12 個月前持股比例 | 職稱範圍、持股股數、分母、資料年月 |
| 總股東人數 | TDCC 股權分散資料 | 取得連續三個月人數 | 股東人數、期別、發布日 |

來源研究已完成：TDCC `1-5`、`1-4` 與 TWSE `t187ap11_L/P` 均已完成官方頁面／schema／實際下載探針。實作仍須保存欄位 mapping、HTTP 狀態、資料筆數與 snapshot hash；不能只靠文件名稱猜欄位。

### 4.2 Source policy status

已按建議方案處理：`config/source_registry.json` 已將 TDCC 加入官方 allowlist，並移出 forbidden sources。仍禁止財報狗、新聞站、公司官網爬蟲、付費報告、社群資料與外部 AI 推論。

本次只處理來源政策與證據；尚未抓取 A 母體完整 ownership release，也尚未改三策略 evaluator。

### 4.3 Fetch cadence

- 股權資料不是每日策略資料；每次 release 可檢查是否有新週／月資料。
- 同一月份只保留最新已發布版本，舊版本保留 snapshot lineage。
- 資料尚未更新時沿用上次 validated snapshot，但顯示 `dataFreshness: stale`、實際 `availableAt` 和期別。
- 新來源失敗時：保留舊資料、記錄 error、不中止價格／策略 release；若無歷史資料，輸出 `unknown`。
- 使用 bounded timeout、retry、rate limit、fixture fallback；不登入、不繞過 CAPTCHA、不抓付費／鎖定資料。

### 4.4 Proposed files

- Create: `pipeline/ownership_inputs.py` — raw → normalized ownership rows。
- Create: `pipeline/ownership_checks.py` — 三個 reference evaluator。
- Create: `pipeline/test_ownership_inputs.py`。
- Create: `pipeline/test_ownership_checks.py`。
- Create: `scripts/fetch_ownership.py` — approved source fetch，輸出受控 cache。
- Modify: `scripts/refresh_snapshot.py` — 載入 validated ownership snapshot；offline 只重算，不假裝 current。
- Modify: `scripts/verify_snapshot.py` / `pipeline/release_contract.py` — schema、lineage、日期與 display-only gate。
- Modified: `config/source_registry.json` — TDCC official public CSV allowlist；正式欄位仍需經 QA。
- Modify: `docs/HEALTH_CHECKS.md`、`docs/SOURCES.md`、`PLAN.md` — source and limitation docs。
- Modify: `.github/workflows/daily.yml` — fetch ownership、verify、build；不能只 upload artifact。

---

## 5. Product/UI plan

### 5.1 Payload placement

- `StockSummary`、`StockDetail`、`RankingRow` 都可帶 `chipReference` 摘要。
- Ranking rows 必須攜帶足夠摘要，避免每個 strategy tab 另外打 API。
- 三個策略使用同一個 `chipReference`；禁止各 tab 自行重算。
- `src/data/api.ts` fail-closed 驗證 nested nullable number、status、period、sourceRefs、`displayOnly: true`。

### 5.2 Display

`src/components/StrategyCard.tsx` 新增小型 `ChipReferenceSummary`：

```text
籌碼參考（不影響策略篩選）
大股東：連續三月上升／未知
董監：較12月前上升／未知
股東人數：連續三月下降／未知
資料期別：2026-06～2026-08 · 來源：TDCC／TWSE OpenAPI
```

規則：

- 三個 tab 都顯示；內容完全相同。
- 不放在 `strategy-count`、候選理由、策略 badge、排序值。
- `unknown` 用「未知／待補資料」，不用紅色「未通過」誤導。
- `stale` 同時顯示實際資料月份與「資料較舊」。
- 詳細檢視顯示三個 raw values、公式、來源、availableAt、限制。
- 不顯示「買進」「籌碼通過即可」等字樣。

### 5.3 Strategy invariants

QA 必須證明加入 `chipReference` 前後：

- 三策略 row code 集合相同。
- 三策略 row count 相同。
- funnel counts 相同。
- PEG、Z、slope、trust rank 不變。
- `isRenderableRow()` 不讀 `chipReference`。

---

## 6. Execution with subagents — default model

### Routing rule

- Parent、workers 全部使用 active `default` profile。
- `delegate_task` children 繼承 default model；不使用 `product-manager` profile，不設定其他 model/provider。
- 不啟動 critic／外部 multi-agent review；QA 由 parent 依本計畫執行。只有 Oma 另行要求才加入 reviewer。
- Shared tree 不並行寫入。每個 code worker 使用 isolated worktree；parent 只在驗收後合併。
- Worker 不得擴大範圍：籌碼資訊只作 reference，不得改策略 gate。

### Stage A — read-only source reconnaissance

**Worker SA-01: Source investigator**

- Input: 本計畫、`docs/HEALTH_CHECKS.md`、`config/source_registry.json`。
- Task: 驗證 TDCC／TWSE OpenAPI 官方來源、欄位、頻率、可下載方式、rate/error 行為；凍結公開 reference 定義。
- Output: `docs/source-evidence/chip-reference-official-sources-2026-09-21.md`、redacted fixtures、field mapping table。
- Forbidden: 登入、繞過 challenge、抓財報狗、修改策略 code。
- Status: 已完成；source evidence 已讀回。SA-02 尚未開始。

### Stage B — contract/backend workers

**Worker SA-02: Ownership contract + evaluator**

- Task: 在 isolated worktree 寫 normalized schema、三個 evaluator、pytest fixtures。
- Must add tests first：嚴格三月 trend、12-month non-strict compare、missing month、duplicate month、zero/invalid denominator、look-ahead、unknown semantics。
- Must not modify strategy candidate selection。

**Worker SA-03: Pipeline/release integration**

- Start only after SA-01 source mapping and SA-02 schema accepted。
- Task: fetch/cache、snapshot lineage、refresh integration、release verifier、offline/stale behavior、workflow changes。
- Must test one-source failure preserves prior snapshot and marks stale/unknown。

### Stage C — UI worker

**Worker SA-04: Reference-only UI**

- Start after schema is frozen; isolated worktree。
- Task: TypeScript types、runtime validation、`ChipReferenceSummary`、three-tab rendering、unknown/stale/accessibility tests。
- Must prove row counts and strategy output unchanged。
- No strategy filter, sort, route, or score change。

### Parent integration

1. Parent reviews SA-01 source evidence and freezes formula/schema.
2. Parent merges SA-02, runs backend gates.
3. Parent merges SA-03, runs release/contract gates.
4. Parent merges SA-04, runs browser/build gates.
5. Parent updates `answers.key` with QA IDs and actual evidence only.
6. Parent creates implementation commit(s); no push/deploy without separate explicit approval.

---

## 7. Bite-sized implementation tasks

### Task 1: Freeze product contract

**Files:** `docs/plans/2026-09-21-chip-reference-indicator.md`, `answers.key`, `docs/DATA_CONTRACTS.md`。

- Add reference-only invariants and `CHIP-REF-*` acceptance IDs。
- Record TDCC source-policy decision and official evidence；不把 source availability 當成策略 blocker。
- Verify no candidate or funnel contract changes。

### Task 2: Verify source definitions

**Files:** `artifacts/chip-source-map.md`, fixture directory。

- Capture official URLs/dataset IDs, field mapping, units, period semantics, and large-holder threshold。
- Redact tokens and retain metadata, not credentials。
- Mark unavailable/locked fields `BLOCKED`。

### Task 3: Add normalized ownership schema

**Files:** `pipeline/ownership_inputs.py`, `pipeline/test_ownership_inputs.py`。

- Implement identity, period, as-of, publication, source, snapshot, numeric normalization。
- Reject malformed units, duplicate conflicting periods, future data, non-finite values。
- Tests RED → implementation → GREEN。

### Task 4: Add three reference evaluators

**Files:** `pipeline/ownership_checks.py`, `pipeline/test_ownership_checks.py`。

- Implement exact trend rules and fail-closed unknown behavior。
- Ensure output includes raw values, period, source refs, formula version。
- Tests prove no proxy from `institutionalDaily` is accepted。

### Task 5: Add source fetch/cache boundary

**Files:** `scripts/fetch_ownership.py`, source adapter module, tests/fixtures。

- Bounded network behavior, rate limit, retry, schema checks, immutable snapshot ID。
- Source failure returns structured error; no empty success and no zero fill。

### Task 6: Integrate release producer

**Files:** `scripts/refresh_snapshot.py`, `pipeline/release_contract.py`, `scripts/verify_snapshot.py`。

- Attach `chipReference` to detail and ranking summaries。
- Preserve old validated ownership snapshot when source has no new period; mark stale。
- Offline rebuild cannot mark ownership current。
- Verify all three strategies receive same reference object semantics。

### Task 7: Update release workflow

**Files:** `.github/workflows/daily.yml`, `config/source_registry.json`, docs。

- Fetch approved ownership data before refresh.
- Do not expose raw source payload in `dist`.
- Verify release before build/upload.
- Keep Cloudflare deploy state separate from data freshness state。

### Task 8: Add TypeScript contract and UI

**Files:** `src/domain/types.ts`, `src/data/api.ts`, `src/components/StrategyCard.tsx`, tests/styles。

- Add nullable `chipReference` types and validation。
- Render reference-only summary in all three tabs。
- Add unknown/stale/error fixtures.
- Prove strategy rows/counts do not change.

### Task 9: Methodology and limitation copy

**Files:** `docs/HEALTH_CHECKS.md`, `docs/SOURCES.md`, `PLAN.md`, methodology UI files if present。

- Explain source, formula, update cadence, large-holder definition, limitations。
- Explicitly distinguish reference info from strategy qualification。

### Task 10: Full verification and release candidate

- Run backend tests, frontend tests, typecheck, build, snapshot verifier。
- Browser smoke test all three tabs and one missing-data fixture。
- Inspect generated JSON programmatically。
- Only after all QA PASS, prepare commit/release. No deployment in this plan.

---

## 8. QA list / answer-key gates

Every result uses current repo contract: `criterion_id`, `result`, `tested_at`, `git_commit`, `evidence_paths`, `notes`. Values: `not_run`, `pass`, `fail`, `blocked`.

### Product and scope

- [ ] `CHIP-REF-01` Three strategy tabs show same `chipReference` semantics。
- [ ] `CHIP-REF-02` Reference status never changes candidate membership, rank, count, funnel, PEG, Z, slope。
- [ ] `CHIP-REF-03` UI explicitly says `不影響策略篩選`。
- [ ] `CHIP-REF-04` No StatementDog/third-party scrape or claim of exact clone。

### Source and data

- [ ] `DATA-OWN-01` Official source URLs/dataset IDs and field mapping evidenced。
- [ ] `DATA-OWN-02` Large-holder threshold and denominator frozen；no guessed threshold。
- [ ] `DATA-OWN-03` Every value has code, market, period, asOf, publishedAt, retrievedAt, source, snapshotId。
- [ ] `DATA-OWN-04` No look-ahead；future publication rejected。
- [ ] `DATA-OWN-05` Three consecutive valid months required for 3-month trend。
- [ ] `DATA-OWN-06` Exact 12-month comparison required for director/supervisor rule。
- [ ] `DATA-OWN-07` Missing/invalid/incomparable values → `unknown`，not zero/fail/pass。
- [ ] `DATA-OWN-08` TDCC allowlist、官方 endpoint、用途與 evidence path 已記錄；未核准的其他來源仍 BLOCKED。

### Pipeline and release

- [ ] `PIPE-OWN-01` Normalizer rejects malformed units, duplicate conflicts, non-finite values。
- [ ] `PIPE-OWN-02` One source outage preserves previous validated snapshot and marks stale/unknown。
- [ ] `PIPE-OWN-03` Offline rebuild never reports current ownership data。
- [ ] `PIPE-OWN-04` Release verifier checks nested schema, formula version, lineage, and display-only flag。
- [ ] `PIPE-OWN-05` Raw payload/credentials never enter `public/`、`dist/`、logs。
- [ ] `PIPE-OWN-06` Existing strategy release remains valid when ownership data unavailable。

### Backend tests

- [ ] `TEST-OWN-01` rising 3-month fixture → pass。
- [ ] `TEST-OWN-02` flat/decreasing 3-month fixture → fail。
- [ ] `TEST-OWN-03` 2-month fixture → unknown。
- [ ] `TEST-OWN-04` latest director holding equal to prior 12-month value → pass。
- [ ] `TEST-OWN-05` missing 12-month point → unknown。
- [ ] `TEST-OWN-06` shareholder count strictly declines → pass。
- [ ] `TEST-OWN-07` one non-consecutive month → unknown。
- [ ] `TEST-OWN-08` institutional flow changes do not affect ownership result。

### Frontend and UX

- [ ] `UI-OWN-01` All three tabs render reference summary。
- [ ] `UI-OWN-02` `unknown`, `stale`, source date, and limitation copy render correctly。
- [ ] `UI-OWN-03` No `unknown`, `NaN`, fake `0.00`, or empty source label。
- [ ] `UI-OWN-04` Keyboard/focus/mobile layout pass。
- [ ] `UI-OWN-05` Existing row count and strategy snapshot tests unchanged。

### Full release

- [ ] `REL-OWN-01` `python -m pytest pipeline scripts -q` pass。
- [ ] `REL-OWN-02` `npm run test:unit` pass。
- [ ] `REL-OWN-03` `npm run typecheck` pass。
- [ ] `REL-OWN-04` `npm run build` pass。
- [ ] `REL-OWN-05` `python scripts/verify_snapshot.py` pass。
- [ ] `REL-OWN-06` Browser smoke test console clean and all three tabs verified。
- [ ] `REL-OWN-07` Git diff check clean; generated release manifest matches code/formula version。
- [ ] `REL-OWN-08` Deployment, Pages completion, and public-domain readback reported separately if deployment later authorized。

### Forbidden PASS conditions

- TDCC/TWSE source not verified but values shown as formal。
- Proxy values relabeled as ownership data。
- Missing months silently dropped from denominator。
- Chip reference changes strategy rows or selection.
- CI/build green used as proof that data source is current。
- Cloudflare Pages deployment used as proof that data refresh succeeded。

---

## 9. Rollback and failure handling

- Feature flag/reference payload absent: UI hides panel or shows `籌碼參考：資料不可用`; strategies continue unchanged。
- New ownership parser fails: retain last validated snapshot with stale label; do not publish partial rows as current。
- Release verifier fails: do not update `latest.json` pointer or deploy。
- UI regression: revert frontend/reference commit; leave prior strategy release intact。
- Source policy rejected later: keep `chipReference` unknown; do not revert strategy rows or use投信代理。
- Never delete previous validated release during rollout。

---

## 10. Handoff state

Plan source blocker handling complete. Current state:

1. TDCC official source allowlist：已處理。
2. TDCC／TWSE field mapping evidence：已處理，證據檔已建立。
3. Large-holder reference definition：已修正為官方 `TDCC級距15（持股1,000,001以上）`；級距16為差異調整，不計入。
4. Freshness policy：已寫入 plan；實作時沿用 validated snapshot + stale，不影響策略 release。

**Approval gate:** 在 Oma double-check 前，不執行 SA-02/SA-03/SA-04，不修改三策略篩選、排序、funnel、候選資格或既有策略 evaluator。通過後，所有 worker 仍使用 default model。
