# 台股 7 類／33 項公開 OSINT 資料盤點

**盤點時間：** 2026-09-08（Asia/Taipei）
**執行 worktree：** `/home/kushi/stock-web-pages-osint`
**標準答案：** 使用者指定的 StatementDog `2330/stock-health-check`；只做 reference/calibration，不做 production candidate。

## 結論先講

- **資料源不是問題的主因。** TWSE、TPEx、MOPS、TDCC 都有免費官方公開資料路徑；TWSE Swagger 實測 143 paths，[3] TPEx Swagger 實測 225 paths，[12] TDCC OAS、JSON、CSV、歷史查詢頁均可達。[19][20][21][22][23][24]
- **現有 repo 不是目標系統。** 本地 site 仍是投信買超＋G/L/cheap/dividend 舊流程；`src/pages/index.astro` 沒有 7 類，`src/data/screener_history.json` 是 0 active／291 archive。
- **已完成本輪 source inventory。** v3 probe 實測 32/32 PASS：TWSE 9、TPEx 7、TDCC 6、MOPS 10；證據：`/home/kushi/.hermes/evidence/2026-09-08-public-osint-stock-screener/public-source-probe-v3.json`。
- **尚未 production-ready。** 缺的是五年／三年歷史 bulk snapshot、期別與分母語義、排名規則、籌碼 aggregate 定義、33 項純計算引擎、candidate/reference 校準；所以目前 verdict 仍是 `BLOCKED`。

## 標準答案目前狀態

既有 sanitized reference artifact 收到 500 個 distinct seven-group records：`/home/kushi/.hermes/evidence/2026-09-07_221223-stock-cron-operations-r10/16-statementdog-reference-7.json`。2330 最近一次記錄：

| group | StatementDog key | passed/count | pass_ratio |
|---|---|---:|---:|
| 排除地雷股 | bomb → safety | 5/6 | 83 |
| 定存股 | cd → dividend | 1/5 | 20 |
| 成長股 | growth | 5/5 | 100 |
| 便宜股 | cheap → value | 0/6 | 0 |
| 轉機股 | turnaround | 1/3 | 33 |
| 續優股 | quality → continuity | 3/5 | 60 |
| 籌碼股 | chip | 1/3 | 33 |

匿名直接抓 StatementDog API 時，public `bomb` 可見，但其他群組可能呈現註冊／付費 locked；這正是為什麼瀏覽器登入資料只能做 reference discovery，不能成為 production 依賴。[2]

## 現有 repo 缺口

| 現況 | 實際證據 | 影響 |
|---|---|---|
| UI 只有舊四個 local score | `src/pages/index.astro`、`src/components/ScreeningRow.astro` | 不可把舊 G/L/cheap/dividend 改名冒充 7 類 |
| builder 依賴外部 monitor tree | `scripts/build_screener_history.py`、`TW_STOCK_MONITOR_ROOT` | 目前 WSL 看不到 `/home/kushi/tw-stock-monitor`；`/root/tw-stock-monitor` 不可讀 |
| 既有 source path 仍含 FinMind/yfinance | `screener/`、`scripts/compute_value_scores.py` | 要移到明確的 free-quota adapter；不能隱式 fallback |
| generated output | `active=[]`, `archive=291`, timestamp 無 `Z` | 不可拿現成輸出當 7×33 production data |
| browser connection | browser harness 仍報 `chrome-not-running`、本機 9222 closed | 本輪不依賴 Chrome；既有 reference artifact 可作 calibration 起點 |

## 7×33 缺什麼、去哪裡找、怎麼找

精確 stable IDs、labels、formula、required fields、source family 已凍結在 `calibration/criteria_registry.json`。下表是執行版摘要。

| group／項目 | 必要資料 | 優先來源 | OSINT 取法 | 目前缺口 |
|---|---|---|---|---|
| safety 1–2：FCF 3/5、五年平均 | 五個完整會計年度 CFO、CapEx | MOPS `ajax_t164sb05`；TWSE/TPEx latest snapshot 做 cross-check。[25][27][15] | `POST isnew=false, TYPEK, co_id, year, season=04`; 解析營業活動現金流與 CapEx；`FCF=CFO-CapEx` | bulk 五年、CapEx row mapping、年度對齊未做 |
| safety 3–4：CFO/NI >100% 3/5、平均 | 年度 CFO、稅後淨利 | MOPS cashflow + income。[26][27] | 同一 ROC fiscal year、同一合併範圍 join；NI=0／缺值 UNKNOWN | bulk、分母 gate 未做 |
| safety 5–6：應收／存貨週轉天數不差 | AR、inventory、revenue、去年同期、elapsed days | MOPS balance/income。[25][26] | 同季歷史 POST；保留表頭與單位 | exact day denominator／quarter vs YTD 語義尚未由 reference 冻结 |
| dividend 1–2：近一年／五年平均殖利率 >6% | 現金股利、日期價格、除權息／股利年度 | TWSE/TPEx valuation、MOPS dividend、歷史價格／估值。[8][9][10][11][17] | 每一 as-of 抓 dated valuation/price；不要把 current price 偷套五年 | yield convention、五年採樣未校準 |
| dividend 3：連五年股利 | 五個連續年度 cash distribution | MOPS dividend、TWSE/TPEx dividend。[8][17] | ROC→Gregorian；同年多期先定義加總規則 | bulk history 未做 |
| dividend 4–5：payout >50% 3/5、平均 | annual cash/share、same-year annual EPS | MOPS dividend + income。[8][26] | 同 fiscal year join；優先 explicit annual EPS，否則四季完整 EPS | bulk、EPS scope/負值策略需測 |
| growth 1：月營收 YoY 連三月 | 三個月 revenue、去年同月 revenue | MOPS monthly revenue；TWSE/TPEx latest monthly snapshot。[5][14][28] | 月份逐月 `POST isnew=false, year, month`；解析本月／去年同期 | bulk history 未做 |
| growth 2–5：近季四項 YoY | 毛利、營業利益、稅前、稅後；去年同季 | MOPS income；TWSE/TPEx latest snapshot。[6][15][26] | 近季與同季去年並列，不能把 YTD 當 quarter | bulk、公布日/as-of gate 未做 |
| value 1/3：PE/PB 五年最低20% | 五年 dated PE/PB history、current PE/PB | TWSE `BWIBBU_d`；TPEx valuation history path 需再驗；每日／月價格。[10][12][17] | 以交易日／宣告的 sampling 保存快照；排除 `-`、非有限值 | TPEx historical endpoint、percentile、tie、universe 未冻结 |
| value 2/4：PE/PB 低於50%公司 | 同日 TWSE+TPEx ordinary-share universe | TWSE/TPEx current valuation + company basic。[4][9][13][17] | 先合併市場與代碼，再 dedupe；ETF／重複 market reject | reference universe／缺值排除未校準 |
| value 5/6：殖利率兩項 | 與 dividend 共用同一 yield input | 同 dividend source | 共用 canonical derived field，不可兩套公式 | yield semantics pending |
| turnaround 1：PB<3 | current PB | TWSE/TPEx valuation。[9][17] | dated finite PB | integration pending |
| turnaround 2：F-score≥8 | 年度 ROA、CFO、NI、長期負債比、流動比、股數、毛利率、資產週轉率，至少 current/prior | MOPS income/balance/cashflow；F-score 九項定義。[25][26][27][34] | 年度 fiscal-aligned，九個 Boolean，缺一完整 F-score UNKNOWN | engine 未做 |
| turnaround 3：PB最低前50 | 完整同日 PB universe | TWSE/TPEx valuation + universe | ascending rank，tie/missing/as-of 先凍結 | BLOCKED，不能自創 tie rule |
| continuity 1：上市>3年 | listing date | TWSE/TPEx basic。[4][13] | 解析 `YYYYMMDD`，以 as-of 算年齡 | integration pending |
| continuity 2：FCF ROE 不下滑 | FCF、股東權益 current/prior | MOPS cashflow/balance。[7][16] | `FCF=CFO-CapEx`; `FCF_ROE=FCF/average equity*100`; fiscal-aligned | bulk、CapEx、as-of 未做 |
| continuity 3：3年 FCF ROE 前20% | 三年 FCF ROE + 完整 universe | 同上 + TWSE/TPEx universe | same date universe、descending rank | rank/tie/missing 未冻结 |
| continuity 4：三年營業利益總和>0 | 三個完整年度 operating income | MOPS income。[26] | annual rows、排除 duplicate/YTD | bulk 未做 |
| continuity 5：PB+PE+殖利率前50 | PB、PE、yield + 完整 universe | TWSE/TPEx valuation。[9][17] | 只能依 reference 得到 composite 定義；不能自訂權重 | **BLOCKED：權重／方向／normalize 未知** |
| chip 1：大股東比重連三月升 | 三個月 major-holder shares + denominator | MOPS internal/major-holder；TDCC dispersion。[23][24][25] | 解析 aggregate label 一次；不把 aggregate+individual 相加 | **BLOCKED：大股東 scope 未冻结** |
| chip 2：董監最新≥12月前 | 兩個月董監 aggregate holdings | MOPS `ajax_stapap1`。[25] | `year/month/co_id/TYPEK`，保留 exact 職稱／aggregate row | aggregate selection 未冻结 |
| chip 3：股東人數連三月降 | 三個月 month-end shareholder count | TDCC 2-22/2-23、query page。[19][20][21][24] | TDCC page 是週資料；每月選最後可用週，保存三月快照 | bulk month normalization 未做 |

## 免費來源的使用規則

- **官方第一順位：** TWSE／TPEx／MOPS／TDCC。
- **FinMind：** 可用免費額度補歷史，但必須先配置 request budget、逐請求 ledger、schema smoke、官方 cross-check；上一輪已出現 IP ban／rate limit，不能盲重試。
- **yfinance：** 可補價格或有限財務欄位；它是 Yahoo Finance 的資料工具，不保證完整 33 項語義。[38] 只能以 secondary provider provenance 保存，不能把缺少的 monthly/annual denominator 猜出來。
- **禁止：** paid API、非官方 proxy、cookies、登入 session、CAPTCHA/WAF bypass、第三方 summary score。

## 可靠性方法論

### Source authenticity

只接受 allow-listed HTTPS host；SearXNG 只是發現層。搜尋摘要不能作證據；先回官方頁／JSON／CSV，再存 source URL、HTTP status、schema hash、retrieved UTC。

### Shape and schema

每次抓取檢查 JSON list/object、CSV header、HTML marker、BOM、target code、market、row count、duplicate identity。schema drift → `PARSE_ERROR`，不可用部分欄位繼續算。

### Time and look-ahead

每筆保留 `as_of`、`period`、`published_at`、`retrieved_at`。只用 as-of 前已發布資料；MOPS request 回應期別必須等於要求期別。五年資料缺一年就 UNKNOWN，不縮 denominator。

### Unit and denominator

保留原始欄名、單位與 consolidated/standalone scope。CFO/NI、payout、turnover days、CROIC 的 denominator 缺失／為零／期間不同 → UNKNOWN。不要把缺失轉 0。

### Cross-source agreement

同一欄位以另一官方表示交叉檢查；不一致產生 mismatch，不平均、不靜默覆蓋。FinMind/yfinance 只可驗證／補洞，不能凌駕官方定義。

### Replay and calibration

先一上市＋一上櫃，再五檔；每檔保存 immutable snapshot，重播結果必須 deterministic。最後對 500 distinct eligible candidate/reference pairs 比較每組 `passed/count/pass_ratio`；reference-only 500 不算 PASS。

## 本輪已執行與下一步

已建立：

- `calibration/criteria_registry.json`
- `calibration/source_registry.json`
- `scripts/validate_public_contract.py`
- `scripts/probe_public_sources.py`
- `tests/test_public_osint_contract.py`
- `docs/answer.key.md`
- `.hermes/plans/2026-09-08_134619-public-osint-stock-screener.md`

已驗證：

- registry tests：8 passed
- v3 official live probes：32/32 PASS
- free fallback transport：0 calls，因 Phase A 不消耗額度

接續順序：

1. 取得可讀 monitor source root，或建立完整官方 source snapshot root。
2. 寫 MOPS/TDCC/TWSE/TPEx normalized adapters 與 fixture。
3. 凍結 turnover/yield/rank/major-holder 語義。
4. 寫純 33-criterion engine。
5. 5-code candidate/reference mismatch。
6. 500-code all-seven gate。
7. UI `z_max`/50% controls、build、release。

**目前不可說完成 production。** 本輪完成的是可驗證的 OSINT source inventory + safe probe，production 仍 `BLOCKED`。