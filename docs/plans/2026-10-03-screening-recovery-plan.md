# 每日選股、網站與 Notion 修復計畫 v2

日期：2026-10-03，Asia/Taipei。
狀態：使用者已對指定合併問題明確回覆「核准上述發布、補跑、Notion 匯入與排程啟用」，可信任授權現已收到，涵蓋修復程式發布、2026-10-02 真實更新、六個留存日與新日歸檔、重試驗證及週一至週五 18:00 Asia/Taipei 排程。授權已解除外部寫入等待，但不代表執行成功；精確來源 CI、GitHub main、正式網站、Notion 獨立 audit 與排程 active version 仍須逐項以實際證據驗收。

## 1. 交付目標與現況

每日由 n8n 在週一至週五 18:00 UTC+8 啟動；先判斷官方交易日，更新網站行情、00631L 指標及三個策略，再把同次發布的三策略入選股票聯集保存至 Notion。網頁、GitHub publication、Notion 必須可以用 date/request/run/hash 相互核對。

前次部署的程式修正不能視為這個目標完成。目前正式網站仍是 2026-10-01 行情，run 為 enriched-20261002-132035-09cf779b0b。舊發布的成長可計算 aggregate 為 0，但財務輸入不足且新診斷欄位未提供，不能當成全部 100 檔都完成評估後零檔符合的證據。最新歷史日期為 10/1；正式 screening export 尚未提供可驗證 JSON。n8n workflow huDBNJDss4KuPmn4 仍 inactive。

使用者 10/3 06:26 的 execution 763 確實完成，但持久化 ledger row 6 是 diagnostic_verified / credential_verified / not_tested，沒有 Actions run、payload hash 或 Notion page ID。手動預設 diagnose，空日期採今天 10/3；這沒有補跑缺少的 10/2。

### 基準時已重現的優先問題

| ID | 問題與證據 | 優先級 | 完成條件 |
|---|---|---|---|
| G1 | 新前端顯示新漏斗，舊發布沒有 growthInputComplete 等欄位，因此出現 —。coverage.ts 將缺欄位映射為 null。 | P1 | 新 current release 有完整可核對數字與逐檔來源；相容性驗證拒絕缺欄位的新發布。 |
| G2 | 舊 100 檔沒有任何完整確認的年度股利；多年度 EPS 成長可推導 9 檔、TTM EPS 12 檔，整體可計算仍為 0。 | P1 | 在真實母體至少一檔走通可驗證成長估值；其他逐檔保留可恢復缺口。 |
| G3 | evaluate_growth_health 有 4 pass / 1 fail 時 aggregate status=fail，growth_health_qualifies 卻要求 aggregate status=pass。實際排除符合 4/5 的股票。 | P1 | 真實 evaluator 輸出 4 pass / 1 fail 或 4 pass / 1 unknown 均依四個已確認通過項目入選健康門檻。 |
| G4 | low_rows 的 append/count 還要求 growth_health_qualified，與價格觀察、健康證據分開的契約不符。 | P1 | 合格調整價、Z≤0、正 slope 的股票不因缺 EPS、PEG 或健康未知被隱藏。 |
| G5 | verify_snapshot 仍要求 growth count≤PEG candidate count，可能攔住使用獨立總報酬本益比的合法成長候選。 | P1 | 發布驗證使用各策略自身漏斗；growth>PEG 可合法通過。 |
| G6 | 股利期間解析接受上半年度／下半年度，卻漏掉真實 payload 的上半年／下半年配獨立年度。 | P1 | 保存的真實欄位形狀回歸測試通過，年度／季度／半年不重複相加。 |
| O1 | manual 預設只有 diagnose，週末空日期不補最近完成交易日；診斷成功容易被誤認資料更新成功。 | P1 | 正常手動入口做實際更新或同次 resume；診斷入口分開，目標日期及結果可見。 |
| O2 | 只有節點／本機測試，沒有 Actions→main→Pages→Notion 的真實閉環與 retry 實數。 | P1 | 真實執行、相同 payload 重試與獨立讀回全部通過。 |
| O3 | 排程未 publish；GitHub／Notion 業務步驟藏在通用 HTTP 與 Code 狀態機。 | P1 | 畫布可辨識各步驟；驗收後 active version 與時區／cron 可核對。 |

目前純函式診斷舊資料得到：同日價格 100；PE reported 80、可合法 derived 12、缺 8；TTM EPS 可推導 12、缺 88；多年度 EPS 成長可推導 9（包含負成長）、缺 91；已確認完整年度股利 0。這些是舊資料診斷，不是新的金融資料發布。

### 本次實作與驗證進度（正式執行前）

以下列出已修改的本機程式及實際測試範圍，不把本機 fixture 或 inactive draft 視為正式資料成功。

| 範圍 | 新版本本機證據 | 正式驗收狀態 |
|---|---|---|
| G3／G4／G5 | 真實五項 evaluator 的 4P1F／4P1U 選股流程、低位策略獨立性，以及 growth>PEG 合法發布回歸已通過。 | 新資料 Actions／網站結果尚待核對。 |
| G6／財務輸入 | 上半年／下半年期間映射、股數可比性與年度／季度重複證據處理已修改；金融來源及 quota 模組有針對性回歸。 | 至少一檔真實 A 母體成長估值恢復尚未證明。 |
| 免費補缺與恢复 | 排程按可閉合的估值證據鏈排序，保存跨日公平 queue，恢復保留最新 checkpoint queue；每日專案上限與實際剩餘帳戶 80% 仍保留。 | 真實 calls／cache hit／queue／執行時間尚未測量。 |
| G1／發布契約 | 新 producer 的 nested `funnel.growthCoverageVersion`、守恆計數、逐檔診斷、canonical export 與新 history projection 已修改；daily 使用 `--require-growth-coverage`，既有 legacy CI 保持相容。 | Python／JavaScript coverage 契約已對齊；最後整合測試與精確來源 CI 仍是發布前 gate。 |
| 網站發布識別 | `/data/publication.json` 包含 date／run／generatedAt 及 exact `latest.json` bytes SHA-256；daily 建立後於 Git publish 前重查；回到頁面或低頻輪詢提示重新載入。producer 及 workflow 39 項針對性測試通過，producer line coverage 96%。 | 新正式 fingerprint、cache header、同日更正與瀏覽器操作尚待驗收。 |
| O1／O3 | 審查中的 n8n inactive draft `f4adc9fb-3aed-42d9-9274-ef23ddb03dde` 已有 58 個可見業務節點；主 manual 選最近完成官方交易日、恢復既有 exact run，診斷另行標示。Python／JavaScript 新 coverage 驗證已對齊；53 項 n8n 測試通過，n8n 模組 line coverage 99.03%、branch coverage 90.80%。 | draft 尚未 publish；真實 Actions、Notion null／0 讀回與重試實數尚待驗收。 |
| 發布權限／秘密 | 唯讀 execution 765 確認 main `2451036717641cd4827dbdc3856f8af8ac462fc6` 與 active daily workflow；Actions secret-name metadata 回傳 403，因此不宣稱已獨立確認 token。新補缺步驟只記 `finmind_token_present=true/false`，不記值。 | 受控執行時確認實際環境存在 token；不要求擴充讀秘密權限。 |

本機最終驗證已通過 437 項 Python、74 項 UI 及 53 項 n8n 測試，typecheck／build 通過；本次受影響前端模組 line coverage 89.07%，逐檔均達 80% 門檻（statement 80.85%、branch 74.02%，不宣稱 branch 達 80%）。新發布重載時 history revision 同步、保留 URL 篩選，以及 eligible universe／未標版本新欄位的回歸已通過。最終整合結果、修改 commit、精確 head CI、正式資料日／run／hash 與 Notion 筆數另以實際執行證據更新。原始六日不可變 legacy revision 不重算、不覆寫。

## 2. 保留的產品決策

- 三策略仍共用官方投信十日買超前 100 的 A 母體，不偷偷扩大母體或放寬估值門檻。
- 成長主策略：總報酬本益比≥1.20，且五项健康至少四項已確認 pass；移除未公開的營收≥15% 額外 gate。
- 五項為三個連續月份營收 YOY 皆正（合計一項），及最近單季毛利、營業利益、稅前淨利、稅後淨利同比各一項。unknown 不算 pass；四個真實 pass 足以達到 4/5。
- 祖魯 PEG 為成長的交叉參考；不重新成為成長、投信新進榜或低位觀察的共同必要條件。
- 保留極端成長／估值外推限制、可比股數基礎、公告截止日與同日價格要求。
- 最終候選可以合法為 0。只有可評估股票已被正確計算、原因可追溯，才可顯示「條件未達」；全無估值時顯示「財務建庫／資料不足」。
- 行情、財務可用性、資料新鮮度、Notion、部署是不同狀態。金融缺漏不阻止已驗證的當日行情更新，但不能把成長策略宣告已恢復。
- FinMind 免費方案；不新增付費來源、不在每日 workflow 執行 LLM、不把 token 放進公開檔案或執行報告。

推薦沿用「n8n 協調、GitHub Actions 做既有 Python 更新與 Git publication、Cloudflare main Git integration 發布」；改成可讀的業務節點。將全部金融運算搬進 n8n 會增加重寫、快取與秘密管理成本，這次不採用。

## 3. Phase 0：凍結基準、文件與 API 查證

工作：
1. 保存現有公開 JSON 的 date/run/hash、100 檔逐項缺漏矩陣、manual ledger 763 與目前 draft。
2. 每個問題記錄「程式修改／本機測試／真實執行／正式網站／Notion／排程」六種不同完成狀態。
3. 逐條對照策略顯示、producer、validator、export，移除文件中過時的成長 15% 或共同 PEG 限制描述。

依據：docs/GROWTH_VALUATION.md；docs/RESEARCH_PROTOCOL.md；src/domain/coverage.ts:25；scripts/refresh_snapshot.py:402、554、1200、1462；scripts/verify_snapshot.py:280；docs/n8n/runtime-evidence.json。

已查可用 API：GitHub node 1.1 的 workflow.dispatch；Notion node 3 的 dataSource.get、databasePage.getAll/create；HTTP Request 4.4 的既有 credential 認證。Notion inline database create 使用官方 2025-09-03 API，database ID 與 data-source ID 分開。Native propertiesUi 的 null／零值／完整 metric projection 仍須先測試，不直接假設支援等價行為。

驗收：問題清單有來源及基準；不把 API schema 查到、metadata GET 或本機 fixture 當成正式寫入成功。

## 4. Phase 1：先修真正的選股與發布 gate

工作：
1. 用 evaluate_growth_health 的真實五條檢查結果判定至少四個 pass；不再使用 aggregate status=pass 當額外必要條件。
2. 低位觀察只由合格價格／回歸位置決定；健康、EPS、PEG 留作證據與欄位，不當隱藏排除條件。
3. 成長發布 gate 改用總報酬本益比漏斗，不要求候選數小於祖魯 PEG 池。
4. 修上半年／下半年等已觀測期間映射；逐條處理 known-invalid、non-positive growth、extreme 與 missing，不把已知負成長報成缺資料。

先寫會失敗的回歸：
- real evaluator→eligibility→build_release→rankings→funnel→export 的 4P1F、4P1U、5P、3P2U 案例。
- 合格調整價、Z≤0、正 slope、健康 unknown、EPS／PEG 缺漏，仍在 lowPosition。
- growth 候選為 1、PEG 池為 0，策略契約／snapshot／export 驗證可通過。
- 真實股利欄位上半年／下半年＋ROC 年度，正現金與確認零現金、年度與季度重複列。

依據與可沿用測試：pipeline/growth_health.py:64；pipeline/test_growth_health.py；pipeline/test_refresh_snapshot.py:9、261、400；pipeline/test_valuation.py:65；pipeline/financial_periods.py:124；scripts/test_verify_snapshot.py；pipeline/test_screening_export.py。

驗收：4/5 不變成 5/5；unknown 不升級 pass；三策略獨立；原始來源 fixture 一路通過發布與匯出。模組須符合至少 80% coverage，新增測試檢查真實資料流而非手造不可能的 aggregate。

## 5. Phase 2：財務補齊、備援與免費配額

來源顺序：既有可靠 cache、同次公開批次、合法可推導值、FinMind 補缺。所有值保留 source、period、availableAt、unit、reported/derived/unavailable 與公式。

| 缺口 | 合法處理 |
|---|---|
| missing_pe | 同日官方正 PE；缺時用同日 raw close／正值、可比、連續四季 TTM EPS。 |
| missing_eps_history | 補已完成年度與季度；CAGR 至少四個完整可比年度，用實際起迄年距。 |
| nonconsecutive_quarters | 補缺季度；兼容 YTD 可以回推單季，EPS 差額另需股數與計算基礎一致。 |
| missing_dividend | 補完整已確認年度／四季／兩半年，按期間去重；提案、抓取日、部分半年不假裝年度確認。 |
| 已知負成長／虧損／極端 | 記 known-invalid／not-applicable／extreme；可展示輸入但不發布不合格估值。 |
| 健康比較缺口 | 同季去年／逐月去年比較，確認金額單位、年度、期間與來源相容。 |

冷 cache 用現有 planner 會產生 308 jobs（財報100、PE20、股利100、月營收88），另有 quota query／retry，超過每天 300 attempts。改成優先關閉「整檔股票還缺的最後證據」，先利用已有 EPS 及可 derived PE 的股票补確認年度股利；避免查已能合法推導的 PE。剩餘任務存持久化 queue，跨日接續。

硬限制：每個臺北曆日所有 runs 合計≤300 HTTP attempts，並≤已查實際剩餘配額的80%；quota query 和 retry 都計數。402/429、quota 不明、token 缺少便停止 supplement；保存 rows、usage、queue、block state。任何午夜後的 request 使用正確曆日或停止，不能透過重跑重置計數。

依據：pipeline/finmind_incremental.py:167、237；pipeline/finmind_client.py；pipeline/financial_periods.py:73；scripts/refresh_snapshot.py:521、554；scripts/fetch_finmind.py；scripts/prepare_finmind_budget.py；docs/OPERATIONS.md。

驗收：100 檔皆有輸入／缺漏診斷；至少一檔真實 A 母體股票具有可查證正 TTM、合法 PE、完成年度 EPS 成長、確認股利且 growthValuation.status=available，才宣告成長估值恢復可用。最終候選不強求非零。若來源與限額不能達成，保持「財務建庫未完成」，列出具體缺口而不報修復完成。

## 6. Phase 3：producer／前端契約與完整網站驗收

工作：
1. 增加明確的 `funnel.growthCoverageVersion="growth-coverage-v1"`；既有通用 `funnel.version="funnel-v2-independent-trust-low-position"` 保持不變。新 current release 的同一 funnel 必須包含 growthInputComplete、growthValuationComplete、growthThresholdCandidates、growthHealthCandidates、growthMissingReasons、growthEvaluationState 及 growthTerminalOutcomes；每個數字由同 run 的全母體 detail 計算。
2. 完整輸入、可計算、門檻達標、健康達標、最終列表的人數要可逐檔核對。缺漏原因可重疊，另提供互斥淘汰階段，避免原因數相加誤超母體。
3. 新 producer 缺字段是發布錯誤；舊 revision 保持不可變、標 legacy。舊 current snapshot 的整組新成長漏斗明示「此發布尚未提供診斷／等待重算」，不混搭未知新欄位與舊 default-zero。前端 src/data/api.ts 做版本／型別驗證；建置／發布 gate 必須核對 producer 與 consumer 相容。
4. 顯示行情完整度與財務完整度兩個百分比、建庫進度／缺漏股票清單、實際交易日／更新時間／run／下一個交易日截止。
5. 成長空名單分清「無可評估股票」「已計算但估值未達」「健康未達」。即使未入選，也能查看已評估股票的輸入與淘汰理由。
6. 核對投信、成長、低位、00631L、歷史、日期／快取／新鮮度，不以單一 growth tab screenshot 代表全站完成。
7. 同版本診斷保留在 canonical export 及新歷史 revision 的 projection，更新 pipeline/history_archive.py 與 history 型別；歷史缺診斷明示 legacy，不依最新規則回推歷史統計。
8. 現有頁面只在 mount 讀一次 latest；在回到頁面或低頻讀取輕量發布識別時提示「有新發布」及重新載入，保留篩選條件。避免頻繁下載完整快照或呼叫金融 API，並驗證同日 correction 也能辨识。

全站回歸矩陣：
- 投信：官方十市場日、TPEx 張轉股、完整兩期 Top10 差集；缺 PE 不隱藏真實新進榜。
- 成長：1.20＋4/5；沒有額外 15% 或 PEG gate；無缺值補零。
- 低位：3.5 年調整價、Z≤0、正 slope、signalEligible；raw proxy 或短歷史不升級正式訊號；健康未知不隱藏合法價格觀察。
- 00631L：交易日等於發布日；今日量除前五個完成交易日均量，排除今日；缺任一期就明示未知。
- 歷史：三策略 rows 與日／月／revision 一致，更正保留舊 revision；搜尋、排序、日期條件、返回最新資料可操作。
- Freshness：頁面開著跨 deadline 自動更新；週末／假日使用下一個應更新交易日；網路失敗 cache 不偽裝最新。

依據：src/App.tsx:262；src/domain/coverage.ts；src/domain/types.ts；scripts/verify_snapshot.py；scripts/verify_daily_freshness.py；pipeline/market_indicators.py；pipeline/test_official_institutional.py；pipeline/test_market_indicators.py；src/App.test.tsx；src/components/DataStatus.test.tsx。

驗收：新發布漏斗沒有因缺 producer 欄位而出現 —；數字、策略股票列表與 detail／export 同源。真實資料不足可以是 0／null，但有逐檔理由及獨立建庫狀態。用 360／768／1440 viewport 的瀏覽器實際驗證核心操作與錯誤／空狀態。

## 7. Phase 4：可讀的 n8n 正常入口與恢复

主 manual 入口做真實更新；診斷分開。未指定日期時以官方 calendar、收盤時間與來源水位選最近已完成交易日；10/3 星期六補缺少的 10/2，已有 exact run 就 resume、已完整完成就回報不重跑。不可單純今天減一天，也不可將 stale Oct1 當作正確 Oct2。

畫布明確呈現：
1. 解析目標交易日／假日與操作種類。
2. GitHub SHA CAS claim／讀取 checkpoint。
3. GitHub Dispatch Actions（native workflow.dispatch）。
4. 找 exact run、Wait、取得狀態、讀取與驗證 artifact。
5. 確認 GitHub main publication。
6. 查找／建立 Notion YYYYMMDD 記錄及 inline database。
7. 查 child data source／row keys，逐檔建立缺少股票列。
8. 獨立讀回 Notion 筆數、值、策略 tags／revision；核對正式網站 exact payload。
9. 更新各階段狀態／Active Revision，呈現 date/run/count/error/Actions 與 Notion links。

Git push 仍由 Actions 的 Publish validated release to main 執行，n8n 畫布清楚標示驗證 publication 的步驟。Cloudflare main Git integration 為唯一正式部署路徑。

API／模式：GitHub node1.1 workflow.dispatch；Notion3 databasePage.getAll/dataSource.get。Notion page create 僅在 null／0／前導零代號／tag／長 provenance projection 的 schema 與實際讀回驗證通過後採 native；否則使用明確命名的 credential HTTP 業務節點。Inline database create 用 HTTP Request4.4、Notion-Version2025-09-03、lowercaseHeaders=false。

保留：dispatch intent 先保存、歧義回應查 exact request title 不重送、SHA CAS、59分鐘 owner＋60秒接管間隔、Wait 後 deadline gate、scheduled19:30 絕對截止、manual override 留審計。Notion 每次間隔至少500ms；429 尊重 Retry-After；不 blanket retry create。

依據與可複製位置：scripts/n8n/engine.cjs:42、126、143、174、245、282；runtime.cjs:33、70；build-workflow.cjs:21、58；test-engine.cjs；test-archive-flow.cjs；audit.cjs:6。不要採 dispatchAndWait：安裝版等待 webhook callback，而既有 daily workflow 沒有該 callback，且 instance 上限3600秒。

驗收：按主 manual 看得到目標日与正式工作結果；診斷明確顯示「不更新行情／不建立歸檔」。使用者不用猜隐藏 mode、Code state 或已刪除的 execution data；sanitized ledger／結果面板提供持久狀態，signed URL、token 不保存。

## 8. Phase 5：真實發布、Notion 與六日回填

先前 09/08 歷史匯入嘗試被自動核准審查拒絕，理由是指定外部寫入尚缺可信任的明確同意。此後使用者已對精確合併問題回覆「核准上述發布、補跑、Notion 匯入與排程啟用」；可信任授權現已收到。範圍包含修復程式的 GitHub feature CI 與非強制 main 發布、2026-10-02 Actions 真實更新及網站驗證、六個真實歷史日與新日 Notion 匯入、same-payload 重試，以及 weekday 18:00 Asia/Taipei 排程。維持 FinMind 免費每日 300 attempts／實際剩餘帳戶配額 80% 約束；不擴大秘密或權限範圍。發布仍先通過精確來源 CI 及 coordinator release gate，以下資料、歸檔、部署與排程項目仍以真實讀回結果判定成功。

受控第一次運作：
1. 對官方確認已完成的缺漏交易日跑一次，保存 source commit、request ID、Actions run ID。
2. 查實際 FinMind quota／attempts／cache hit／queue／耗時；金融欄位映射不符合時修 adapter 回歸，不放寬資料可信政策。
3. Snapshot／freshness／完整策略發布驗證通過後，Actions 發布 main、上傳 canonical export 與 publication。
4. 正式網站 latest、00631L、history、export 同日同 run；查 exact bytes/hash/cache headers。
5. Notion 根資料庫中每個日期一筆 YYYYMMDD 記錄，內含同名 inline DB。存三策略聯集、tags、各策略 ranks、metrics、input evidence／缺漏、公式、revision/hash；代號使用文字保留前導零。
6. 獨立讀回筆數、唯一碼／Row Key、策略集合與重要 numeric/null 值，與 canonical export 對照。

回填六個實際留存日期：20260908、20260911、20260918、20260923、20260924、20261001。Pin已驗證 repo commit、index/month/revision hash，保留原始入選資料、缺值與 legacy 標示；不重新篩選、不呼叫 FinMind。完成本次新日期後同樣獨立 audit。

Same payload 重試：相同 date/request/run/hash 不新 dispatch、不多建 root page／child DB／stock row。更正 append 新 revision，舊列保留，全部驗證後才切 Active Revision。合法零檔與來源失敗、假日 skip、歸檔失敗、部署待完成各自記錄。

依據：pipeline/screening_export.py:118、166；.github/workflows/daily.yml:126；scripts/verify_history_production.py；scripts/n8n/legacy.cjs；test-legacy.cjs；test-archive-flow.cjs；audit.cjs。

驗收：資料真實到 GitHub、Pages、Notion 三端；現有六日＋新日各有可讀的實際紀錄；第二次 retry 的實際筆數與 run 不增加。Notion read credential 成功不等於 create/write 成功，Actions CI 成功不等於資料 refresh 成功。

## 9. Phase 6：排程啟用與營運交付

驗收前述階段後 publish n8n：週一至週五 18:00 Asia/Taipei，先 official holiday check；晚間每10分鐘 checkpoint 同次 recovery。目標18:45，scheduled最晚19:30；逾期或失敗保持上次有效資料並明確顯示未更新，不新增假零檔紀錄。

交付報告逐項列：
- 問題ID、修改commit、測試結果與 coverage。
- 真實 request／Actions run／published commit／payload hash。
- 網站實際資料日、00631L、三策略人數與財務可計算人數。
- FinMind 實際 calls／剩餘配額／queue，不用估計冒充測量。
- 七個日期的 Notion page／childDB／dataSource、expected／actual count、retry 實數。
- n8n activeVersion 與 cron／timezone／checkpoint／manual入口。
- 真實 bootstrap 尚缺資料與恢復操作；沒有真實證據的項目標未完成。

本機必要檢查：

    .venv/bin/python -m pytest pipeline scripts -q
    npm run test:unit
    node --test scripts/n8n/test-*.cjs
    npm run typecheck
    npm run build
    .venv/bin/python scripts/verify_snapshot.py
    .venv/bin/python scripts/verify_daily_freshness.py --market-date YYYY-MM-DD --data-dir public/data --config config/tracked_symbols.json
    .venv/bin/python scripts/verify_history_production.py --base-url https://stockscreener.andyshih.uk/ --expected-dir public/data

實際 node schema／SDK 驗證、security review、npm audit／pip audit、git diff review 都在發布前完成。最終狀態不得只寫「測試都通過」；必須附產品與營運閉環的真實證據。
