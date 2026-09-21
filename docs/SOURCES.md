# 資料與部署來源查核

查核日期：2026-09-21。官方文件可能更新，實作P0須保存當時能力、schema與小型測試回應。此文件區分「文件確認」和「實際API成功」，不把前者當後者。

## 1. 資料來源分工

| 來源 | 用途 | 關鍵限制 |
|---|---|---|
| TWSE | 上市母體、行情、法人、估值與財務批次 | 最新OpenAPI不自動等於歷史API；各資料集須核對單位、日與完整性 |
| TPEx | 上櫃對應資料 | 不可只用buy排行頁代表完整法人報表，未列股票不一定是0 |
| TDCC | 股權分散、持股級距、股東人數 | 官方公開週 CSV；以 `資料日期`、級距、歸戶口徑保存；不抓私人帳戶資料 |
| FinMind | 按股歷史價量、法人、營收、財報、公司行動 | 免費／付費能力不同；財務期末不等於公告日 |
| yfinance | 私有行情核對、研究備援 | 非Yahoo官方工具；不能預設可以公開再散布取得的資料 |

## 2. 官方端點與能力

### TWSE

- [OpenAPI目錄](https://openapi.twse.com.tw/)及其[Swagger JSON](https://openapi.twse.com.tw/v1/swagger.json)：用來確認當前批次API。實作記錄實際endpoint、欄位、日期、單位與資料筆數，不自行添加未聲明的歷史參數。
- 董監事持股正式端點：[上市公司 `t187ap11_L`](https://openapi.twse.com.tw/v1/opendata/t187ap11_L)、[公發公司 `t187ap11_P`](https://openapi.twse.com.tw/v1/opendata/t187ap11_P)。兩者 schema 均含 `資料年月`、`公司代號`、`職稱`、`目前持股`；先按明示職稱範圍加總，再與同月發行股數對齊。
- 大股東交叉資料：[持股逾10%大股東名單 `t187ap02_L`](https://openapi.twse.com.tw/v1/opendata/t187ap02_L)。只作交叉研究，不替代 TDCC 股權分散趨勢。
- [T86三大法人日報](https://www.twse.com.tw/fund/T86?response=html)：本次讀到投信買進／賣出／買賣超「股數」欄位。沒有個股投信實際成交金額。
- [TWT44U投信日報](https://www.twse.com.tw/fund/TWT44U?response=html)：本次讀到相同股數概念。歷史日期JSON請求及全市場參數仍需部署runner smoke，不宣稱已測通。

候選使用官方每日完整買賣资料；若無法取得完整買賣雙方向，不能以買超頁缺列推導零。保留原始標頭以驗證schema變更。

### TDCC

- [官方開放資料專區](https://www.tdcc.com.tw/portal/zh/stats/openData)已列出[股權分散表 `1-5`](https://opendata.tdcc.com.tw/getOD.ashx?id=1-5)與[發行人董監分戶保管 `1-4`](https://opendata.tdcc.com.tw/getOD.ashx?id=1-4)。
- `1-5` 實際探針 HTTP 200，CSV header 為 `資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%`，資料按週最後營業日發布。
- 籌碼參考初版使用 `1-5`：`持股分級=17` 人數作股東人數；級距15（1,000,001以上）比例作高持股級距參考。級距16為差異數調整，不計入。方法頁顯示官方級距定義，不冒充 StatementDog 內部門檻。
- `1-4` 只作分戶保管輔助資料，不能冒充完整董監持股；完整董監持股改用 TWSE `t187ap11_L/P`。

### TPEx

- [OpenAPI目錄](https://www.tpex.org.tw/openapi/)及[Swagger JSON](https://www.tpex.org.tw/openapi/swagger.json)：文件確認 `/tpex_3insti_trading` 為上櫃投信買賣超彙總表。
- 該API直接請求在本次研究環境出現403，僅能列「文件確認，執行環境可取性未確認」。P0需在預計使用的GitHub runner測試；403不是0筆股票。
- [舊版投信買超排行頁](https://www.tpex.org.tw/web/stock/3insti/sitc_trading/sitctr_result.php?l=zh-tw&o=htm&t=D&type=buy)：頁面欄位以張數表達、且為buy排行，不能當成所有買賣雙向完整資料。

如官方完整bulk確實無法取得，免費FinMind可按股慢速補歷史，但不能在覆蓋不足時發布「完整跨市場十日排行」。此缺口是P0上線能力gate。

### FinMind

統一資料入口為 `GET https://api.finmindtrade.com/api/v4/data`。已確認常見按股請求含 `dataset`、`data_id`、`start_date`、`end_date`；是否適用仍以個別資料集為準。Token透過Authorization header，不記錄值。

| 資料集 | 規劃用途 | 權限／注意事項 |
|---|---|---|
| `TaiwanStockInfo` | 代碼與目前市場／產業 | 轉板可能多列，最新date不是歷史上市資格證明 |
| `TaiwanStockPrice` | 按股歷史OHLCV | 指定日全市場查詢有會員限制 |
| `TaiwanStockPriceAdj` | 可選還原價 | 文件標示限backer/sponsor；免費基準不能依賴 |
| `TaiwanStockPER` | 歷史估值欄位 | 當期EPS／PBR口徑要核對 |
| `TaiwanStockTradingDate` | 交易日參考 | 與官方市場日曆及特殊休市核對 |
| `TaiwanStockInstitutionalInvestorsBuySell` | 法人股日歷史 | 投信name為`Investment_Trust`，buy/sell；全市場按日模式需權限 |
| `TaiwanStockMonthRevenue` | 月營收 | 月份、date、create_time不能混成公告時間 |
| `TaiwanStockFinancialStatements` | 損益與EPS | 原始季度EPS跨公司行動需對齊股數，不能盲加TTM |
| `TaiwanStockBalanceSheet` | 權益、現金與負債 | 歷史期別／公司涵蓋需實測；不是每家公司每季都有 |
| `TaiwanStockCashFlowsStatement` | CFO、折舊攤銷等 | 科目與累計／單季需對照原始報表 |
| `TaiwanStockDividend` / `TaiwanStockDividendResult` | 股利、除權息事件 | 宣告／除權息／發放日分開處理 |
| `TaiwanStockCapitalReductionReferencePrice` | 減資事件參考 | 不能只看價格倍率忽略现金與股數變化 |
| `TaiwanStockSplitPrice` / `TaiwanStockParValueChange` | 分割／面額變更 | 具體覆蓋與調整公式仍需官方fixture驗證 |
| `TaiwanStockDelisting` | 下市事件線索 | 不等於完整歷史母體與下市公司財報 |

原始文件：[技術面](https://finmind.github.io/tutor/TaiwanMarket/Technical/)、[籌碼面](https://finmind.github.io/tutor/TaiwanMarket/Chip/)、[基本面](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/)。上表為能力索引，不保證所有公司、日期及欄位均完整。

月營收文件例子的2019年3月資料date為2019-04-01；create_time僅2026-04-21起記錄，旧資料空字串。create_time為建立時間，也未必等於公司正式公告時間。三報schema主要為date/stock_id/type/value/origin_name，未確認具備公告時間。[基本面時間語義](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/)

實作保存first_seen_at、fetched_at、published_at（可空）、period_end、版本與content hash。歷史可得時間不足時只能做明示延遲假設研究；今日定期保存能改善日後前向證據，不能修復過去所有未知版本。

[API用量文件](https://finmind.github.io/api_usage_count/)確認 `GET https://api.web.finmindtrade.com/v2/user_info` 可讀user_count/api_request_limit，超限可能回402。[快速開始](https://finmind.github.io/quickstart/)有不同登入條件額度說明，產品以實際帳號剩餘額度限速，不假定永久固定上限。

### yfinance與公開用途

[官方README](https://github.com/ranaroussi/yfinance)說明它並非Yahoo認可／官方工具，資料API用途有personal-use限制。[Price Repair](https://ranaroussi.github.io/yfinance/advanced/price_repair.html)說明股利、分割及價格可能需修復。使用修復功能也要保存處理版本與異常，不保證修復結果總是正確。

[FinMind免責與資料授權](https://finmind.github.io/Disclaimer/)說明API使用資格不直接授予對外再散布權。是否可公開某欄位或衍生結果須確認原始來源用途。這是發布設計限制，不能以購入FinMind會員或換成圖表繞過。

## 3. 部署選擇與官方依據

| 主題 | 已確認事項 | 官方來源 |
|---|---|---|
| Pages Direct Upload | 可用預先建好的資產；專案類型有切換限制 | [Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/) |
| Git integration | 類型不能直接轉Direct Upload；官方另允許關閉Git自動build後用Wrangler | [Git integration](https://developers.cloudflare.com/pages/configuration/git-integration/) |
| Actions發布Pages | 可在CI build後用Wrangler及Secrets發布 | [CI教學](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/) |
| Pages回滾 | 成功production deployment可回滾，preview不是回滾目標 | [Rollbacks](https://developers.cloudflare.com/pages/configuration/rollbacks/) |
| Pages容量 | Free每月500次平台build、每站20,000檔、單檔25MiB；不是對Direct Upload部署次數的同義保證 | [Limits](https://developers.cloudflare.com/pages/platform/limits/) |
| GitHub排程 | 預設UTC、執行default branch；可能延遲／丟棄；公開repo長期無活動可能停用 | [Schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) |
| Actions額度 | GitHub Free私有repo包含2,000分鐘／月；標準runner公開repo使用有免費規則；額度帳號共用 | [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) |
| R2持久化 | 可用S3相容API；token限制到bucket；需自行啟用服務 | [S3](https://developers.cloudflare.com/r2/get-started/s3/)、[認證](https://developers.cloudflare.com/r2/api/tokens/) |
| R2免費額度 | Standard 10GB-month、100萬Class A、1,000萬Class B／月；超額收費 | [R2 pricing](https://developers.cloudflare.com/r2/pricing/) |
| Cache不是資料庫 | Actions cache有淘汰條件，不能當唯一不可重建資料來源 | [Dependency caching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching) |
| GitHub Pages替代 | GitHub Free可用公開repo；私人repo的Pages方案權限不同 | [Getting started](https://docs.github.com/en/pages/getting-started-with-github-pages) |
| Netlify Free比較 | 新制每月300credits、正式部署15credits／次，每日部署可能超過免費額度 | [方案](https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/credit-based-pricing-plans/)、[價格](https://www.netlify.com/pricing/) |

GitHub目前也支援IANA timezone，本計畫仍用簡單UTC cron `17 15 * * *` 對應台北23:17。不要把排程觸發寫成準時完成保證。

完整快照發布是應用層的一致性設計，不是全球所有客戶端瞬間切換的保證。前端須檢查run_id與快取，資料已驗證但部署失敗時保留同版供重試。GitHub與R2狀態標記分清validated與published。

## 4. 研究假設與已查核事實分開

三路Top100、20檔每日補庫、四年＋120日bootstrap、12%停損、品質閾值與部位限制是本產品的待驗證參數，不是以上來源證明有效的投資法則。

資料完整／公式正確不能推出年化50%。投信排行造成選樣偏誤是根據篩選机制的推論；需透過全市場基準、漏失清單與樣本外研究量化。
