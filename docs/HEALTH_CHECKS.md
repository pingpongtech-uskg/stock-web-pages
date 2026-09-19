# 7 類 33 項公開資料健診

這一頁重建的是我們自己的公開資料規則，不複製財報狗的內部資料庫。每一項都必須有數值、期間、可得時間與來源，才會被判定為通過或未通過；資料不足會保留為「待補資料」，並且要有指定的取得路徑。

## 目前追蹤標的的取得路徑

| 資料 | 首選來源 | 回退來源 | 正規化結果 |
| --- | --- | --- | --- |
| 月營收與 YOY | MOPS/XBRL、TWSE/TPEx OpenAPI | FinMind TaiwanStockMonthRevenue、公司 IR | `monthly_revenue` |
| 損益（營收、毛利、營業利益、稅前、淨利、EPS） | TWSE/TPEx 財報 OpenAPI、MOPS XBRL | FinMind TaiwanStockFinancialStatements、公司 IR | `income_statement` |
| 資產負債（現金、應收、存貨、權益、有息負債） | MOPS XBRL、TWSE/TPEx | FinMind TaiwanStockBalanceSheet、公司 IR | `balance_sheet` |
| 現金流與資本支出 | MOPS XBRL、TWSE/TPEx | FinMind TaiwanStockCashFlowsStatement、公司 IR | `cashflow` |
| 股利、殖利率、本益比、股價淨值比 | TWSE/TPEx OpenAPI、公司股利公告 | FinMind、yfinance 價格與已發布股利 | `valuation` / `dividend` |
| 董監、大股東、股東人數 | MOPS、TDCC 股權分散 | 公司 IR | `ownership_monthly` |
| 3.5 年價格與公司行動 | yfinance Adj Close（`auto_adjust=False`） | Yahoo chart adjusted close；FinMind raw close 僅作代理 | `daily_price` |

上市公司第一批實作會直接使用 TWSE OpenAPI 的 `exchangeReport/BWIBBU_ALL`（PE/PB/殖利率）、`opendata/t187ap05_L`（月營收）、`opendata/t187ap06_L_ci`／`t187ap07_L_ci`（一般業損益與資產負債）及 `opendata/t187ap45_L`（股利）。上櫃公司改接 TPEx 對應 endpoint；現金流、股權分散與公告日缺口再由 MOPS XBRL、FinMind 或公司 IR 補齊。

## 33 項規則與實作狀態

目前程式已固定七類門檻：績優 3/5、成長 4/5、籌碼 1/3、便宜 5/6、轉機 1/3、排除地雷 6/6、定存 5/5。`pipeline/health_checks.py` 是唯一的規則入口；`unknown` 不會計入通過。

第一個已接上的正式欄位是「月營收 YOY 連續三個月大於 0」。每日先以公開投信十日買超前 100 建立 A 母體，再對 A 的每一檔抓官方結構化資料與 yfinance 代理，並以公告日保存 point-in-time 版本。這樣做完後，頁面會顯示每一列的實際值、比較期間、來源與取得時間，而不是只顯示一個總分。

## 取得順序

1. 先對 A 母體前 100 檔抓五年年度／季度財報、五年股利與估值、十二個月股權分散；建立原始列與欄位 mapping。
2. 由原始列計算 FCF、CFO/淨利、ROE、週轉天數、F-score、殖利率與五年百分位。
3. 逐項執行 33 個條件，保存 `availableAt`、`period` 與 `sourceRefs`。
4. 只有在該檔 33 項均有可比較資料後，才把「健診完成」納入榜單；資料仍不足的檔案仍可研究，但會列出具體缺口與回退來源。

## 已接入的官方快照（A 母體前 100 檔）

發布器會各抓一次 TWSE OpenAPI，再依股票代號保存到 `healthInputs`：

- `exchangeReport/BWIBBU_ALL`：同日 PE、PB、殖利率，以及可計算市場百分位的估值母體。
- `opendata/t187ap05_L`：當月、上月、去年同月營收與出表日。
- `opendata/t187ap06_L_ci`：最近可得一般業損益欄位（營收、毛利、營業利益、稅前／稅後淨利、EPS）。
- `opendata/t187ap07_L_ci`：最近可得一般業資產負債欄位（資產、負債、權益、應收、存貨、每股淨值）。
- `opendata/t187ap45_L`：股利年度、現金股利、股票股利與公告日。

目前以官方當期快照判定 PB<3、當期殖利率>6%、當期 PE/PB 市場百分位等可證明條件；畫面會標示「當期橫截面代理」。五年序列、股權分散與 F-score 仍需下一階段用 MOPS/XBRL、TDCC 與公司 IR 歷史資料逐期回填，不能用單一最新值冒充。
