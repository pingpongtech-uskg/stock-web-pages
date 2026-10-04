# StockScreener：10/2 起完整資料與每日更新計畫

更新日期：2026-10-04 09:57 Asia/Taipei。10/2 v6 網站、12檔 Notion 選股、13/13完整快取及獨立還原已驗證；同 payload 正常重跑已證明不新增寫入。最新 source 已由 promotion979／ledger608 非強制發布並讀回，main CI成功；97節點 primary 已啟用且獨立讀回。下一個排程為10/5週一18:00 Taipei；尚未發生的交易日執行不列為已驗證。下列歷史段落保留當時時間及未完成狀態，不代表目前狀態。

## 目前已驗證的交付狀態

| 項目 | 已驗證結果 | 驗收／日常運作界線 |
| --- | --- | --- |
| 網站 10/2 行情 | v6 data commit `11ea3f75963779efa5d275425ea86f08103e4267`；Actions `37165596357`；request `stockscreener:20261002:v6`；run `enriched-20261004-084306-55b9107f29` | 網站v6已驗證；後續資料日須各自讀回 date／run／hash |
| 00631L | 10/2 成交量99,743,650股／前五日均量118,730,520股＝0.8400843355187866倍 | 每日沿用七個必要交易日的真實來源，再補新日 |
| 成長股 | 神基3005、漢唐2404、技嘉2376，各5/5；母體100、估值輸入完整62、可計算20、入選3 | 缺資料20、已知無效58、極端2、低於門檻17、入選3，合計100；缺值不可造值 |
| 投信與低位階 | 完整11交易日重算；10/2與10/1 Top10成員相同，排名及買超改變，新進0正確；低位階10檔 | 每日維持完整窗口及可追溯來源 |
| Notion 20261002 | 三策略聯集12檔、1子資料庫、12唯一鍵；獨立969／972審核192個數值欄位，其中32 null、3真零 | 已完成 v6 選股歸檔及獨立數值驗收 |
| 完整快取 | 13/13附件讀回驗證；最新 manifest `cc2811ee0c73c8bd9ff6bc2fa3e6d9247a54171819da71699c84ad433fcd7276` | 指標仍 `metricsComplete=false`，20檔真實財務缺漏如實保留 |
| 快取還原 | 實際 Notion→Git bridge975／ledger604；root `4caa6356e3bd750296dec218e021d18e305dec5e`；Python CLI exit0，100股票、11法人日、7量能日、179檔，移除 token 執行 | 10/5僅還原 readiness；尚未取得、計算或發布10/5行情 |
| 重試冪等 | 正常重跑978／ledger607 `already_complete`；沿用 Actions37165596357，無新寫入 | 已完成 v6 同 payload 重試驗收 |
| 每日自動化 | 97節點、無AI；週一至週五18:00 Taipei，另有有限晚間恢復及官方交易日檢查 | 2026-10-04T01:57:28Z獨立讀回ACTIVE=true、activeVersion與draft相同；下一次10/5排程尚未執行 |
| 最新程式修復 | source `e0ab2fc34fb6cd7b29b4260e8a634dd98e085b92`，parent為v6 data commit；feature CI `37168953934` SUCCESS；211 n8n／994 Python通過，npm／pip audit 0 | promotion979／ledger608 `main_verified`；main CI `37169443313` exact e0ab SUCCESS，active version已讀回 |

快取完整指已取得的原始資料、逐日全市場窗口、逐檔輸入及缺值原因能完整保存與還原，不表示每檔每项財務指標都可合法計算。銀行缺毛利、缺EPS、負基期等仍明確unknown；20檔估值證據鏈缺漏不能用零替代。

最新還原 descriptor SHA為 `d50652c9a6ba8a5b6e6e4627e8fa19cc344c84ef1b0aff90c3566588055fecc7`。修復後，restore bodies 每次由 CAS 讀回後重新取得的 bytes 建立，嚴格重新計算 SHA。實際974原生 POST 回201並取得SHA，但一般 Git tree GET 回404；獨立審核對同一SHA的 recursive view 以一次 GET 回200，修復後975 bridge完成讀回驗證；只能宣稱已驗證這條讀回備援，不能宣稱已證實 timeout。不同 recursive views 的有界讀重試不重播寫入。977因缺少 `ciRunId` 在任何網路操作前拒絕；979使用已驗證的 feature CI ID 執行非強制 promotion，ledger608讀回main_verified；main CI37169443313完成SUCCESS。

先前 v5 失敗（歷史）：n8n954／Actions37162842189在 TPEx 來源 HTTP520 三次重試後停止，未進入FinMind、未發布新行情。v6已恢復成功完成狀態。同日來源備援只允許傳輸故障或明確5xx，重用相同市場、交易日、URL及已驗證原始SHA，重新解析核對；日期／內容錯誤不能回退，不以10/1冒充10/2。來源仍保留原取得時間及 `verified_cached_after_refresh_failure`，不宣稱新抓取。

成功快取的 `lastVerifiedCache` 保存完整原producer來源；修訂失敗不能清掉該描述，只有新版本全部verified才切換。只有active hash而缺完整來源時仍不能猜測恢復。

排程啟用實證：primary `huDBNJDss4KuPmn4` activeVersion `e3d3ed10-3187-4cc8-950d-0a8bcfdf9b49` 與draft一致，97節點、AI節點0；節點／connections／settings無變更。timezone `Asia/Taipei`，主cron `0 18 * * 1-5`、晚間恢復cron `*/10 18-20 * * 1-5`，原19:30截止保持。下一次應為2026-10-05 18:00；只證明設定與active readback，不宣稱未來已成功跑完。

三個臨時診斷／審核helper `TIgXL66Fg0bw5NqQ`、`LVptJ9GOVkBNSb0R`、`2MMHlOWXUb6JycKs` 已獨立確認archived=true；restore probe先還原neutral inspect。source publication helper `u955NdZSl26dxfJJ` 是只供受控程式／文件發布的臨時 inactive helper，不參與日常排程。canonical97節點SDK 300,502 bytes透過只移除空白的esbuild版本292,305 bytes符合300k工具限制，97節點參數一致；正式Git仍保存canonical源碼。

## 交付範圍

使用者最新要求：「沒必要補之前的資料，我要10/2開始資料完善且每個交易日更新」。以 2026-10-02 為第一個正式修復資料日；之後每個交易日更新網站及同日 Notion。停止新增更早日期的選股歷史發布及通用舊日選股回補工程。使用者進一步明確要求：10/2 必須完整重算，必要的 10/1 與往前比較／計算資料需留存在 Notion，供每日更新和快取備援。既有紀錄保留。

n8n 是唯一日常排程入口，週一至週五 18:00 Asia/Taipei；先查官方交易日及來源日期，休市日跳過。GitHub main 更新觸發已連接的 Cloudflare Pages。手動與自動共用同一發布／歸檔流程。

指標計算仍可能需要往前資料：投信當日與前日的十日窗口共有 11 個交易日；財報同比、TTM EPS、多年度 EPS 成長需要對照期間。這些作為必要計算輸入及運作快取，與舊日選股歷史回補分開。使用者已明確選擇完整 10/2 計算，因此必須建立必要啟動窗口，不能改成從 10/2 等待累積。日常流程只使用 n8n 排程、確定性程式、GitHub Actions／Pages 及 Notion API；不使用 AI agent 或 LLM 節點。

## 起始問題與修復紀錄（歷史狀態）

| 項目 | 實際證據 | 修復與驗收 |
| --- | --- | --- |
| 正式網站仍是舊行情 | latest.json 資料日 10/1；run enriched-20261002-132035-09cf779b0b；00631L 仍為 10/1、0.74 倍 | 真實 10/2 行情、前五個完整交易日成交量及發布 fingerprint 必須一致 |
| 投信關注沒有新進榜 | 已發布的 10/1 與 9/30 Top10 成員相同、排名順序不同；這兩日的新進榜 0 合理。10/2 完整官方十一日窗口已重算：Top10 成員相同、排名及淨買超數字改變，新進榜確為 0；尚未正式發布 | 顯示資料／比較日期；只有完整兩個窗口才能判定 10/2 新進榜，缺資料不能顯示有效的零檔 |
| 成長股最後為 0 | 舊資料 100 檔中已有 9 檔五項健診全通過，但正式成長估值可計算 0 | 分開健診與估值門檻；補齊真實估值輸入，不為了產生候選而放寬規則 |
| 財務品質 0/100 誤導 | qualityStatus 實際 pass 0／fail 0／unknown 100 | 顯示明確通過、未通過、未知、不適用、未提供；未知不等於失敗 |
| 健診計算缺陷 | 稅後淨利兩期可能混用總額／母公司口徑；未來發布資料可能越過 asOf | 比較共同同一欄位；按評估日先過濾原始資料，再由 YTD 推單季 |
| 其他健診把缺資料當失敗 | 非成長分類存在 blanket unknown-to-fail；AR／存貨、歷史股利等缺欄位亦判失敗 | 未知保留未知；已知完整輸入且未達條件才失敗；不影響三策略的既定門檻 |
| 自動發布未完成閉環 | 新日 Actions 因 TPEx 歷史來源失敗；10/2 未發布／未有股票歸檔，主排程 inactive | 完成一次真實網站發布、Notion 值讀回與同 payload 重試，才啟用主排程 |

2026-10-03 的補跑 v2（n8n 890／Actions 37146944320）卡在 9/28 休市日：TPEx 空報表保留了合法日期、24 欄與零列，但增加 presentation metadata，嚴格欄位集合檢查因此拒絕。已用 artifact 11282556816 的完整 SHA／lineage 與原始 1,859 bytes 回應確認；10/2 CSV 本身成功取得且 SHA 與獨立快取一致。修復以官方日曆先跳過休市日，兼容這種合法空報表，不能將交易日未知資料冒充零。尚未重新成功補跑。

補跑 v3（n8n 901／Actions 37152242700）已成功取得官方法人窗口，但股權參考採集在 20:40:13–20:48:25 UTC 超過 8 分鐘並停止；未進入 FinMind 補件、未發布新行情、未寫入完整 Notion 快取。原始採集最多對 100 檔逐檔查三個月、逐日 GET／POST，缺全域 deadline。修復加入總採集 180 秒／40 次 request、歷史額外最多 20 次，先保存官方批次與已驗證舊值；缺漏仍標示 stale／unknown。主流程已恢复一般輸入、93 節點 inactive；待修復 CI 通過才以新 request 重跑。

完整原始執行證據及既有歸檔審核保存在 docs/n8n/runtime-evidence.json。當時已發布程式來源 65cb430ab55017fbc6064fd43d1c55be48c462b1，feature CI 37154225271／main CI 37154413616 success；n8n 903／904、ledger 144／145 驗證非強制 feature／main 更新；這不是 10/2 行情發布。

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

新核心與格式 adapter 已通過本機整合與審查；v6 正式補件實際35次HTTP attempts、rolling requests35、allowed attempts300，47個補件任務完成34個。這是任務數，不是股票數；100檔輸入皆保留。僅驗證token存在布林值，不讀取或展示FINMIND_TOKEN；不使用付費整市場資料集。

## 四、10/2 投信啟動資料與後續日資料

先優先使用完整官方 TWSE／TPEx 日快照，驗證來源日期、rows、股／張單位及普通股資格。小數張必須精確換成整股，不能先截小數再乘 1,000；buy − sell 必須等於 net。已修復並以 0.036 張＝36 股、98／0.059／97.941 張＝98,000／59／97,941 股等案例驗證。無效 common-stock 數值使整份來源失敗，不默默漏列。已保存的 TPEx 10/2 OpenAPI 真實回應有 910 rows，原始 SHA-256 2d058996bf67a375e152f381dda1a8610c32cf3ecd1ed31240c89ac7fd020402；只有這一天的完整來源，不是十一日完成證明。

既有 institutional_universe 的 dailyRows 每日只有 81–89 列，因為已篩成當前 100 檔，不能當全市場窗口。當日與前日十日排名需固定十一日：9/16、9/17、9/18、9/21、9/22、9/23、9/24、9/29、9/30、10/1、10/2。

首日必須完整呈現 10/2，因此取得並保存這個必要窗口，含 10/1 比較基準；不能以累積中取代已要求的完整計算。不能為了發布把 unavailable 變成有效零檔。

免費單股區間備援已真實驗證：v3 request／n8n 857／Actions 37094557187 共 4 attempts（用量 1、資料 3）。用量觀測時 limit／remaining 皆 600；這是當時數值，不是現在餘額。1785、3105 十一日完整；1240 缺 9/21。1240 的 10/2 buy／sell／net 都是明確零值。

獨立 readonly 864／ledger 112 驗證 checkpoint artifact 11262758917 的 lineage、ZIP digest、三筆 raw／normalized SHA 及來源參數。1240 的 9/21 整天五種法人皆缺；不能將缺列補零。三筆快取可零 HTTP 重用；診斷未推網站或進 Notion。必要缺日只做有界定點重查／官方交叉證據，不廣泛重跑已完成部分。

10/2 起每天先保存完整官方日來源；往後只加入新日並滑動窗口，避免每次重新回補舊日期。

新的只讀來源證據：使用者目前開啟的相同 sitcStat 路由，以 GET、完整 type／date／searchType／id／response 查詢可取得 10/2 CSV；原始 SHA-256 231878b83ee9b668debc6ce7d457660fb6c50f5f17d635ac730d71729367bf8b，cp950 編碼，28 排名列。這份 buy 報告只有買超側，張數取整，3131 的 36 股顯示為 0 張；不能當完整精確全市場日資料。已核對同路由 JSON 也只有 buy／sell 各 28 列且取整，不能作完整來源；此前 POST 失敗不代表此 GET 也失敗。

已從官方頁面與其公開 frontend script 找到完整三大法人明細：GET insti/dailyTrade，type=Daily、sect=AL、date=YYYY/MM/DD、response=csv；原始 cp950，以股數列示含零股。10/1 完整報表 6,279 列／793 普通股，10/2 6,190 列／788 普通股；後者與已保存 OpenAPI 的全部 788 普通股、2,364 個投信買進／賣出／淨額數值完全一致。實作改用此完整來源，逐日股票集合不同，不能以缺列補零。

## 五、網站與 Notion 發布閉環

n8n 可見節點涵蓋：選交易日、GitHub 原生 dispatch、claim/checkpoint、Actions 狀態、main publication 驗證、canonical export、網站真實 bytes fingerprint、Notion schema／當日頁／子資料庫／逐列讀回。實際 main 資料提交在 Actions 的 Publish validated release to main；n8n 必須再讀回確認，不能只看 dispatch 成功。

網站顯示資料日、更新時間、run、品質狀態。刷新日期及 00631L 日期必須與官方已完成 session 一致。實際已核對 10/2 量 99,743,650 股、前五日均量 118,730,520 股、0.8400843355 倍；原始 September／October 回應與七日必要窗口已留存，並已正式發布 v6。旧版 aggregate growth funnel 未提供時保留未知，仍顯示該發布實際保存的逐檔五項健診與估值缺漏，不捏造 input audit。區分「未取得資料」、「已知不符」及「有效零候選」。

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

早期本機驗證（歷史）：657 項 Python、86 項 n8n、84 項 UI 通過，typecheck／build／diff check 通過。受影響三份前端 production 檔案 line coverage 分別 87.78%／100%／100%，合計 91.95%；branch 75.88%，不宣稱 branch 達 80%。配額模組 combined line coverage 93%，health_checks 99%、growth_health 94%、官方投信模組 80%。npm audit 漏洞 0、secret review 0、未解決 HIGH／MEDIUM 0。實際 Python producer 在無網路 fixture 下產生新每小時摘要，通過實際 n8n validator；已過期額度的三筆快取重用也以 0 attempts／3 cache hits 通過。上述不是新金融資料發布。


## 歷史完整來源與快取實作驗證（狀態以當時時間為準）

已用 34 次官方公開請求（17 個日曆日期、兩市場）取得上述十一個完整交易日，FinMind 使用 0 次；原始 bytes、來源參數、hash 與驗證 sidecar 先保存，再篩 Top100。獨立離線重算使用原始來源重新驗證、0 HTTP，證明 10/2 與 10/1 前十成員相同，但排名與十日淨買超不同，因此本日新進榜 0 是有效計算結果。10/2 排名前四：2303 67,309,456 股、2884 35,453,077 股、1303 30,334,589 股、6505 29,716,498 股；尚未發布網站。

新增確定性 Python assembler／producer 先核对 Git／run／publication／config／export lineage，逐份重解析十一日原始 TWSE／TPEx，核对全市場逐日代碼集合與 buy／sell／net，然後產生九角色 gzip 快取分片與完整證明。calendar／00631L 同步保留原始月回應、官方休市證據及必要七日窗口；Actions restore source cache 在選母體前，成功 artifact 與失敗 partial checkpoint 分開。金融缺漏保留 null，不能靠快取完整掩蓋指標缺漏。

第二批本機驗證：843 Python、106 n8n 通過；官方來源模組 line coverage 81.80%、producer／export／assembler scoped line coverage 96%；不宣稱 branch coverage 達 80%。独立 peer 沒有 HIGH／MEDIUM。這批尚未發布，主 workflow 尚未接上完整快取。

Notion 能力驗證尚未完成：881／ledger115 證明遠端 Code 不支援 zlib，於 Notion 請求前停止；882 無結果 ledger，不能宣稱成功或安全重試；883／ledger116 只讀證明無已掛載診斷附件。884／ledger117 用同一個原始 multipart wrapper，證明 prepareBinaryData／getBinaryDataBuffer 可用，172-byte 公開測試 gzip 的 hash 完全相符，沒有 Notion 請求。下次真實 tiny upload 必須保持 workflow 版本直到執行完成，逐階段保存去敏結果，成功後再恢復 inspect。完整原始語意由有界 Python 驗證，Notion 讀回驗證可信 producer 證明與壓縮 bytes，不降級成無界解壓。


發布前補充審查已關閉兩处 assembler 固定 temp symlink 覆寫：以同目錄隨機 mkstemp、target／ancestor guard、atomic replace 與失敗 cleanup 驗證。股利 producer、補件 planner、cache assembler 統一檢查 approvedAt／publishedAt／availableAt／exDate／exDividendDate 的所有已知日期；任一日期不完整、無效或超過資料日都不採用，確認的真零仍保留。新增 RED 後 GREEN 測試與獨立 peer 已通過；npm／pip audit 實際漏洞皆 0。

真實 Notion 885／ledger118 已完成唯一小型公開測試檔的 create upload、multipart send、附件建立與新頁讀回，全部 HTTP 200。既有獨立下載 gate 對實際回傳的 S3 virtual-host hostname 拒絕，所以壓縮 bytes hash 讀回仍待下一次只讀驗證；不重複上傳、不宣稱完整快取成功。主排程仍未啟用。


第二批已實際發布 source commit 8eec7416be8146cb45b483cc1fe53489f4a22973：feature n8n887／ledger120／CI37146657826 success；main n8n889／ledger121／CI37146801114 success，皆非強制 ref 更新。Notion891／ledger126 已只讀驗證同一測試附件的 172-byte 壓縮 hash 完全相符；encoded credential query 被舊整條 URL 路徑檢查誤判，改成只檢查 pathname 並通過獨立測試。沒有新增第二份附件，沒有寫股票或完整快取狀態。

已啟動新受控 request stockscreener:20261002:v2，主 workflow890／Actions37146944320，精確 source8eec、main、workflow_dispatch、資料日10/2。沒有續跑舊失敗 v1；n8n已保存 dispatch 與 exact run checkpoint。該次執行後來失敗，詳見下一段；正式資料、完整 Notion 快取、同 payload retry 和主排程啟用尚未完成。


v2 真實 runner 在 Fetch official institutional universe 失敗，Actions37146944320／job111272755562；金融補件沒有執行，新行情未發布。主 workflow890／ledger129 完成 failure_metadata，沒有建立成功股票歸檔。執行結束後恢復正常 operator；沒有盲目重送失敗 request。匿名讀 job logs 被 GitHub 拒絕（403），下一步使用既有 GitHub credential 做一次固定 job 的去敏只讀診斷，確認錯誤後再決定修正。

當時新增還原整合已通過 926 項 Python 測試及獨立審查：還原僅補財報／營收／股息輸入，既有有效輸入優先，官方新輸入最後覆蓋；同日價格、asOf、法人與策略結果均由當日重算。六項可選 restore dispatch inputs 必須同時提供並逐项驗證，Actions 維持可信 main 程式，資料 commit 僅作還原來源。主流程的 Notion 備份／Git 資料橋仍待完整實際驗收。

已知跨年限制：新的官方日曆檢查要求完整窗口年份都有權威日曆，缺少前一年時明確停止；不可把未覆蓋日期當作休市。跨年窗口日曆保留／還原需在宣稱全年無人操作前完成驗收。

完整 Notion 備份與還原資料橋已部署為停用的 93 節點 n8n 草稿（version 09651afd-e56b-4434-ae93-1fe8b9848f2c），157 項本機測試與 SDK／全部節點設定驗證通過，獨立參數讀回一致。附件保存發送及附加前持久化意圖；不確定結果先查既有上傳／附件，避免重試重複。還原資料使用 manifest 原始時間建立確定性、無程式、無父 commit 的 Git 資料樹，交由可信 main 程式驗證；同份快取在不同操作時間產生相同 commit。尚未驗證實際完整快取上傳／日常還原；主排程繼續停用。

本機跨年修復已通過原始日曆重解析、11／7 日窗口及同儕審查：單年度格式相容，跨年使用相鄰兩個已驗證年度；1 月後續日可從已還原的兩年度快取選出前年日曆，普通同年度還原不誤判。n8n 95 節點產物尚未發布／部署，遠端仍為 93 節點停用版本。必要前一年快取缺漏明確停止，不自行假設休市或以舊排行替代。

2026-10-04 新來源65cb430已通過main CI，95節點停用草稿參數／connections獨立讀回一致。受控10/2 v4（n8n905）已啟動；其operator版本ed1bf930-9a1d-49f0-b6a6-3aab5ea09533維持不變至terminal。尚未完成新行情、Notion完整快取及正式排程驗收。


## 歷史10/2發布與快取續作

Actions37154771933 已成功，來源65cb430，資料非強制發布至 main a0e12ef2a4d5c90ff3f7af9dabe1a6bd51071f92。發布資料日2026-10-02，成長候選3檔、低位觀察10檔、投信新進榜0檔；成長估值輸入完整62/100。00631L今日99,743,650股、前五日均量118,730,520股，動能0.8400843355。Notion選股列已讀回，尚不宣稱全部財務指標或完整備份完成。

905／ledger157在完整快取驗證遇cache_latest_hash。實際只讀診斷906返回GitHub檔案描述1140bytes；907改讀固定commit公開原始檔，4822862bytes的SHA256與publication.json完全一致。修復維持固定40hexcommit、精確路徑、無認證／無redirect、有界binary與原始bytes雜湊，不降低驗證。34項聚焦測試與95節點SDK通過。908只恢復同一成功Actions／payload的Notion快取，不重跑金融API。

瀏覽器實際重新載入仍顯示舊10/1快取並提示網路讀取失敗；新增前端loader真實payload檢查，正式網站畫面驗收尚未完成。排程維持停用。月底月營收到期佇列修復已通過71項獨立測試；當日來源失敗的有界自動再執行仍待整合與審查。


## 歷史驗收進度（2026-10-04，當時狀態）

前端修正3e9ae6已發布，瀏覽器實際顯示10/2、00631L 0.84倍、估值輸入完整62檔／可計算20檔、神基3005／漢唐2404／技嘉2376三檔成長股。三檔均確認5/5健診。投信Top10與10/1成員相同，排名與買超數字不同，因此新進榜0；低位觀察10檔，三策略去重共12檔。20檔估值證據未齊，不宣稱100檔皆可估值。

97節點修復2b5aec1已通過feature CI37158678981及main CI37159128796；本機187項n8n測試通過，獨立審查清除兩處自動重試MEDIUM。真實925／ledger187證明結構式JSON guard在n8n環境接受JSON資料、拒絕symbol key／class／Date／保留鍵。所有新metadata nodes沿用既有GitHub credential。

927已驗證完整cache artifact並進入13附件上傳；第一份upload ID已保存，但執行在第二次pre-send checkpoint前停止、沒有terminal ledger。929／ledger200只讀確認同一upload仍pending；930／ledger201以小型資料執行實際generated checkpoint成功，所以不宣稱已證實OOM。932以精確SHA釋放確認停止的owner，獨立公開讀回released=true，保留原upload ID與intent；診斷helper已恢復只讀。正在減少重複攜帶完整base64檔案並增加checkpoint例外紀錄；完整附件讀回、Notion日頁完成、實際還原、同payload重試及排程啟用仍未完成。

20節點還原驗證workflow LVptJ9GOVkBNSb0R建立於Andy Shih個人專案根目錄；已讀回no-retention及既有credentials，預設inspect／inactive，尚未執行。其只建立驗證的資料Git objects，不會發布10/3、dispatch Actions、呼叫金融API或寫Notion。主排程保持停用，直至真實閉環驗收。


2026-10-04 07:17 Taipei 狀態：Oct2網站已由正式payload顯示00631L0.84倍、成長估值输入完整62／可計算20／候選3。Notion已驗證8/13快取附件；933在169-byte分片binary準備停止，939獨立GET確認同一upload pending，940只以exactSHA CAS重置已證實尚未送HTTP的旗標，保留8附件與uploadID。941正續傳既有Actions37154771933／v4，不重跑provider。Selector .first修復與terminal manual-resume guard已在GitHub main2a89810，featureCI37161070694／mainCI37161197334 success；179既有測試99.71%line、92.50%branch。13附件全部讀回、Notion獨立審核、完整還原與排程啟用仍待完成。

2026-10-04 07:24 Taipei：941／ledger319完成Oct2v4：screening complete、deploy verified、Notion complete、cache verified13/13。945／ledger320獨立Notion審核12行、12unique、1日期childDB；192數值欄、32null、3zero均符合發布payload。944正執行實際Notion→資料限定Git restore bridge；非10/3篩選，無Notion寫入、無Actions dispatch、無網站發布。銀行單數IncomeAfterTax漏接已TDD與peer修復；真實六家稅後YoY轉可判定，負基期仍unknown。新來源4ecc39待CI發布及Oct2重新正規化；195n8n tests99.62%line／91.77%branch、982Python tests、npm及pip audit無已知漏洞。完整Python還原、fresh-run零POST重用、最新修正版資料及排程仍待驗證。

2026-10-04 07:35 Taipei：獨立Python CLI從固定data-only commit112974c39d5aa126d6ea60efca540497fd986ac6完整還原PASS：11法人交易日、7成交量交易日、100股票、179檔，metricsComplete=false如實保留。949同payload重試ledger373 already_complete，原Actions37154771933保持，不重跑API／不重建Notion。944遇新Git tree短暫404，948遇GitHub API剝除commit message末尾LF；均已找到實際差異，新增read-only1/2/4秒有限重查＋單LF精確投影相容，沒有放寬其他SHA／tree／parent／timestamp驗證。201n8n tests99.62%line／91.90%branch，1c9c1bb待CI發布；950正再次實際bridge驗證，fresh-run零POST及排程仍未完成。4ecc39銀行alias已mainCI37161934178 success，但當前Oct2v4數據仍需重新正規化，預定v5修正版。
