# StockScreener：10/2 起完整資料與每日更新計畫

更新日期：2026-10-03。整體交付仍進行中；程式本機修復、source CI 成功或診斷成功，不等於新行情已發布。

## 交付範圍

使用者最新要求：「沒必要補之前的資料，我要10/2開始資料完善且每個交易日更新」。以 2026-10-02 為第一個正式修復資料日；之後每個交易日更新網站及同日 Notion。停止新增更早日期的選股歷史發布及通用舊日選股回補工程。使用者進一步明確要求：10/2 必須完整重算，必要的 10/1 與往前比較／計算資料需留存在 Notion，供每日更新和快取備援。既有紀錄保留。

n8n 是唯一日常排程入口，週一至週五 18:00 Asia/Taipei；先查官方交易日及來源日期，休市日跳過。GitHub main 更新觸發已連接的 Cloudflare Pages。手動與自動共用同一發布／歸檔流程。

指標計算仍可能需要往前資料：投信當日與前日的十日窗口共有 11 個交易日；財報同比、TTM EPS、多年度 EPS 成長需要對照期間。這些作為必要計算輸入及運作快取，與舊日選股歷史回補分開。使用者已明確選擇完整 10/2 計算，因此必須建立必要啟動窗口，不能改成從 10/2 等待累積。日常流程只使用 n8n 排程、確定性程式、GitHub Actions／Pages 及 Notion API；不使用 AI agent 或 LLM 節點。

## 現況與已證實問題

| 項目 | 實際證據 | 修復與驗收 |
| --- | --- | --- |
| 正式網站仍是舊行情 | latest.json 資料日 10/1；run enriched-20261002-132035-09cf779b0b；00631L 仍為 10/1、0.74 倍 | 真實 10/2 行情、前五個完整交易日成交量及發布 fingerprint 必須一致 |
| 投信關注沒有新進榜 | 已發布的 10/1 與 9/30 Top10 成員相同、排名順序不同；這兩日的新進榜 0 合理。10/2 尚未驗證 | 顯示資料／比較日期；只有完整兩個窗口才能判定 10/2 新進榜，缺資料不能顯示有效的零檔 |
| 成長股最後為 0 | 舊資料 100 檔中已有 9 檔五項健診全通過，但正式成長估值可計算 0 | 分開健診與估值門檻；補齊真實估值輸入，不為了產生候選而放寬規則 |
| 財務品質 0/100 誤導 | qualityStatus 實際 pass 0／fail 0／unknown 100 | 顯示明確通過、未通過、未知、不適用、未提供；未知不等於失敗 |
| 健診計算缺陷 | 稅後淨利兩期可能混用總額／母公司口徑；未來發布資料可能越過 asOf | 比較共同同一欄位；按評估日先過濾原始資料，再由 YTD 推單季 |
| 其他健診把缺資料當失敗 | 非成長分類存在 blanket unknown-to-fail；AR／存貨、歷史股利等缺欄位亦判失敗 | 未知保留未知；已知完整輸入且未達條件才失敗；不影響三策略的既定門檻 |
| 自動發布未完成閉環 | 新日 Actions 因 TPEx 歷史來源失敗；10/2 未發布／未有股票歸檔，主排程 inactive | 完成一次真實網站發布、Notion 值讀回與同 payload 重試，才啟用主排程 |

完整原始執行證據及既有歸檔審核保存在 docs/n8n/runtime-evidence.json。最新已發布程式來源 3c5fcb6b24281e9c892727079e46762f9b759459，feature CI 37094159114／main CI 37094354929 success；這不是 10/2 行情發布。

## 一、五項成長健診與估值規則

五個檢查逐項保存 pass／fail／unknown、實際數值、比較期間及來源：

1. 最新可取得、連續三个月的月營收，同比各自大於 0；不能用三月合計或單一正值替代。
2. 最新可取得單季毛利「金額」，相對去年同季年增率大於 0；不能以毛利率替代。
3. 最新可取得單季營業利益金額，相對去年同季年增率大於 0。
4. 最新可取得單季稅前淨利金額，相對去年同季年增率大於 0。
5. 最新可取得單季稅後淨利金額，相對去年同季年增率大於 0；兩期必須是同一淨利口徑。

保留已核准門檻：至少 4/5 確認通過，另需總報酬本益比（本站整理）可計算且 ≥1.20。移除原本未揭露的營收成長 ≥15% 額外門檻。健診合格不等於最終估值合格。

未發布季度／月營收不能用；periodEnd 不是發布日期。缺明確發布證據時使用保守既有申報期限；已知提前發布且期間完成者依實際證據處理。YTD 差分要求前季同口徑完整資料；不能用已混入未來前季的快取結果。去年基期非正值維持未知，不擅自更改負基期年增率定義。

本機已完成同欄位與 asOf 修復。對原正式 10/1 資料離線重算：健診合格 9、確定未達 1、未知 90；500 個檢查為 pass 52／fail 3／unknown 445。3293 五項皆通過：6–8 月營收 YoY +17.18%、+25.86%、+24.80%；2026 Q2 對 2025 Q2 毛利 +14.60%、營益 +8.64%、稅前 +36.32%、稅後 +33.58%。這是既有真實資料重算，不宣稱取得新財報或恢復最終估值。

其他分類缺值修復同步進行。股利歷史必須來自五個連續、完整、已確認年度；重複同年、斷年、未發布、未確認資料不能直接通過。真實已知負 CFO、低殖利率仍可失敗。既有 ≥500 價格筆數只保留為明示代理，不宣稱已驗證正式上市三年。

## 二、缺少估值輸入的補救順序

每檔建立 input audit，明列來源為 reported／derived／missing／not-applicable，缺漏原因可以重疊，但最終分類守恆。

- missing_pe：先查同日官方 PE；只有現價與可驗證同口徑 TTM EPS 皆合法時，才推導 PE = 價格／TTM EPS。
- missing_eps_history：補連續、可比的完整年度及季度 EPS；不能用營收成長當 EPS 成長，不能把代理當正式資料。
- nonconsecutive_quarters：補缺季；只有一致期間、口徑與股數基礎支持時才由 YTD 差分。年度／季度資料不能重複加總。
- missing_dividend：取得已確認完整年度現金股利。只有來源證明完整年度現金股利為零，才寫零；查無資料不是零。
- 股本變動、拆股與重編：確認可比 basis 後才計算多年成長，不以未調整 EPS 任意外推。

優先補能關閉整檔估值證據鏈的項目；先利用已合法可推导的值，再花 API 額度。余下任務保存 queue，可續跑；網站同時顯示未補齊的原因。

## 三、FinMind 免費每小時限制

官方規則：[快速開始](https://finmind.github.io/en/quickstart/) 為未帶 token 300 次／小時、驗證帳戶 token 600 次／小時；[使用次數](https://finmind.github.io/api_usage_count/) 提供 account limit 與 user_count。先前每日 300 限制是錯誤設定，已由使用者修正。

現行專案自己的保守規則：最近連續 60 分鐘所有 runs 合計最多 300 次 actual HTTP attempts，且不超過已查實際剩餘帳戶額度的 80%。這不推測供應商是整點重置還是滑動窗口。沒有人工每日 300 上限。

每次 HTTP 前持久化唯一事件與 UTC 時間；用量查詢、失敗、重試都計數。跨小時、午夜、同日重跑不清空近期事件；財務與投信補件共用同一 ledger 及 Actions concurrency。402／429 依實際 Retry-After 停止；quota 不明或 token 缺失時禁止資料請求。

配額觀測有有效期，不能靠重查同一個窗口無條件擴張 allowance；過期後須有新的實際用量證據。舊 checkpoint 沒有逐次時間時保守遷移近期計數，不當成空 ledger。rows／queue 跨小時及跨日保留，trusted artifact 恢復合併事件、不重置配額。新每小時摘要與舊每日格式分開驗證；損壞 checkpoint 的使用量保留 null，不能宣稱零。

新核心與格式 adapter 已通過本機整合與審查；尚未以新限制執行正式補件。不使用付費整市場資料集，不取回或展示 FINMIND_TOKEN。

## 四、10/2 投信啟動資料與後續日資料

先優先使用完整官方 TWSE／TPEx 日快照，驗證來源日期、rows、股／張單位及普通股資格。小數張必須精確換成整股，不能先截小數再乘 1,000；buy − sell 必須等於 net。已修復並以 0.036 張＝36 股、98／0.059／97.941 張＝98,000／59／97,941 股等案例驗證。無效 common-stock 數值使整份來源失敗，不默默漏列。已保存的 TPEx 10/2 OpenAPI 真實回應有 910 rows，原始 SHA-256 2d058996bf67a375e152f381dda1a8610c32cf3ecd1ed31240c89ac7fd020402；只有這一天的完整來源，不是十一日完成證明。

既有 institutional_universe 的 dailyRows 每日只有 81–89 列，因為已篩成當前 100 檔，不能當全市場窗口。當日與前日十日排名需固定十一日：9/16、9/17、9/18、9/21、9/22、9/23、9/24、9/29、9/30、10/1、10/2。

首日必須完整呈現 10/2，因此取得並保存這個必要窗口，含 10/1 比較基準；不能以累積中取代已要求的完整計算。不能為了發布把 unavailable 變成有效零檔。

免費單股區間備援已真實驗證：v3 request／n8n 857／Actions 37094557187 共 4 attempts（用量 1、資料 3）。用量觀測時 limit／remaining 皆 600；這是當時數值，不是現在餘額。1785、3105 十一日完整；1240 缺 9/21。1240 的 10/2 buy／sell／net 都是明確零值。

獨立 readonly 864／ledger 112 驗證 checkpoint artifact 11262758917 的 lineage、ZIP digest、三筆 raw／normalized SHA 及來源參數。1240 的 9/21 整天五種法人皆缺；不能將缺列補零。三筆快取可零 HTTP 重用；診斷未推網站或進 Notion。必要缺日只做有界定點重查／官方交叉證據，不廣泛重跑已完成部分。

10/2 起每天先保存完整官方日來源；往後只加入新日並滑動窗口，避免每次重新回補舊日期。

新的只讀來源證據：使用者目前開啟的相同 sitcStat 路由，以 GET、完整 type／date／searchType／id／response 查詢可取得 10/2 CSV；原始 SHA-256 231878b83ee9b668debc6ce7d457660fb6c50f5f17d635ac730d71729367bf8b，cp950 編碼，28 排名列。這份 buy 報告只有買超側，張數取整，3131 的 36 股顯示為 0 張；不能當完整精確全市場日資料。正在驗證同路由 JSON 的完整側別、日期及精度；此前 POST 失敗不代表此 GET 也失敗。

## 五、網站與 Notion 發布閉環

n8n 可見節點涵蓋：選交易日、GitHub 原生 dispatch、claim/checkpoint、Actions 狀態、main publication 驗證、canonical export、網站真實 bytes fingerprint、Notion schema／當日頁／子資料庫／逐列讀回。實際 main 資料提交在 Actions 的 Publish validated release to main；n8n 必須再讀回確認，不能只看 dispatch 成功。

網站顯示資料日、更新時間、run、品質狀態。刷新日期及 00631L 日期必須與官方已完成 session 一致。旧版 aggregate growth funnel 未提供時保留未知，仍顯示該發布實際保存的逐檔五項健診與估值缺漏，不捏造 input audit。區分「未取得資料」、「已知不符」及「有效零候選」。

Notion 使用 Notion account 2，根資料庫 StockScreener；每個交易日一個 YYYYMMDD 頁面／inline 股票子資料庫。

日頁保存 MarketDate、RunId、RequestId、PayloadHash、SourceGitCommit、PublishedGitCommit、資料品質、三策略筆數、發布／歸檔狀態及可去敏錯誤。股票子表保存代碼（文字）、名稱、市場、多選策略標籤、各策略排名、價格、PE、TTM EPS、股利／殖利率、EPS 成長、總報酬本益比、五項健診狀態與比較期間、估值／資料來源及缺漏原因。

收錄當日任一三策略入選股票的聯集，一個股票一列、多策略用 tags。缺值存 null，真零存 0。資料不完整的失敗日可以保存失敗 metadata，但不可偽裝成成功的零股票紀錄。

同 payload 重試不得增加日頁、子資料庫或股票列；同日合法修正保留 revision 證據，不能默默覆蓋不同 payload。發布成功但 Notion 失敗時只恢復 Notion 步驟，不重新抓行情／重算／推 GitHub。

## 六、完整運作快取與 Notion 備援

選股子資料庫與完整運作快取分開。每個交易日日頁附 market-cache-v1 manifest 及 gzip 分片，保存完整全市場法人原始來源／正規化日資料、官方交易日曆、00631L 計算窗口及實際發布所用逐檔財務／估值輸入。必要的 10/1 基準和十一日啟動窗口亦保存；當前 Top100 子集不能冒充全市場完整快取。

每個分片保留資料日、來源日期／URL／單位、schema、來源 lineage、原始／壓縮 SHA-256、大小、列數與代碼集合 hash；分片壓縮最大 4 MiB、解壓最大 32 MiB。Notion 免費方案單檔上限 5 MiB，所以使用多片，不能把約 8.1 MB 壓縮的現有 100 檔明細塞成單檔。檔案透過既有 Notion account 2 上傳並掛在日頁，逐片重新讀回、匿名下載、驗證 hash／資料日／覆蓋率後才標記 complete。簽名下載 URL 有期限，每次從授權頁面取得新 URL，不永久保存 URL 當備援。

完整快取 bytes 不代表每個財務指標皆可計算；明確記錄各項 coverage 與 null／0，缺來源／缺日期仍為 pending，不能提供正式比较基準。來源完整度要求依角色與完整代碼集合驗證，不能靠檔案存在判成功。最新日行情不能由前日快取冒充。前日快取只提供真實比較、既有合法財報及恢復用途。

同一 hash 重試重用已驗證附件與檔案 IDs；修正版保留原版本，只有新版本全部讀回成功才切換 active hash。寫入不明時先讀回再重試。发布成功但快取／Notion 歸檔失敗，只恢復歸檔，不再次抓行情、計算或推 GitHub。快取不得含 token、帳戶身分、配額 ledger 或原始診斷日志。執行仍為確定性程式，不依賴 AI agent。

## 七、驗證與啟用順序

1. 凍結健康檢查、未知顯示及每小時配額修復；TDD、有效模組至少 80% line coverage、peer review，修完 HIGH／MEDIUM。
2. 整合 Python、UI、n8n 契約；typecheck、build、差異／secret review。精確 feature head CI 成功後，非強制發布 main，再獨立確認 main CI 與 Pages JS/CSS bytes。
3. 使用新受控 request revision 取得 10/2 真實日行情與指標輸入；不重送已知失敗舊 request。報告 actual attempts、account observation、cache hit、queue、完整／缺日數及實際耗時。
4. 驗證 10/2 日期、00631L 今日量／五日均量、Top10／比較窗口、五項健診與可計算估值、canonical export 及 fingerprint。合格 0 檔只在來源完整且逐檔淘汰原因可驗證時接受；不強迫產生標的。
5. 推 main 後獨立讀正式網站 date／run／hash；建立 20261002 Notion 日紀錄並讀回 rows、tags、rank、每個 numeric null／0／數值；完整運作快取與 10/1 比較基準逐片驗證並標記完成。
6. 同 payload 重試，讀回證明沒有重複頁／DB／列、没有再次 FinMind 查詢或 GitHub dispatch。測一次 Notion 復原，不重跑發布。
7. 通過真實閉環後啟用主 workflow huDBNJDss4KuPmn4 的週一至週五 18:00 Asia/Taipei；官方休市跳過，當日來源未就緒則在有限截止時間內重試，避免發布昨日當今日。
8. 交付實際 code commit、CI、10/2 data run、網站 fingerprint、Notion 日頁／筆數、workflow active version 與排程 readback。沒有這些證據，整體仍未完成。

最終本機驗證：657 項 Python、86 項 n8n、84 項 UI 通過，typecheck／build／diff check 通過。受影響三份前端 production 檔案 line coverage 分別 87.78%／100%／100%，合計 91.95%；branch 75.88%，不宣稱 branch 達 80%。配額模組 combined line coverage 93%，health_checks 99%、growth_health 94%、官方投信模組 80%。npm audit 漏洞 0、secret review 0、未解決 HIGH／MEDIUM 0。實際 Python producer 在無網路 fixture 下產生新每小時摘要，通過實際 n8n validator；已過期額度的三筆快取重用也以 0 attempts／3 cache hits 通過。上述不是新金融資料發布。
