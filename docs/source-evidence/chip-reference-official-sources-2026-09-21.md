# 籌碼參考官方來源探針

查核時間：2026-09-21 13:52 Asia/Taipei
目的：處理籌碼參考資訊的資料來源 blocker；本文件不代表三策略已修改。

## 已驗證來源

### 1. TDCC 股權分散表

官方開放資料頁：

- https://www.tdcc.com.tw/portal/zh/stats/openData
- https://www.tdcc.com.tw/portal/zh/smWeb/qryStock

官方開放資料下載：

- `https://opendata.tdcc.com.tw/getOD.ashx?id=1-5`
- HTTP 200
- Content-Type: `text/csv; charset=UTF-8`
- 探針下載大小：2,369,802 bytes
- CSV header：`資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%`
- 探針資料最新日期：`20260918`

TDCC 查詢頁說明：資料按每週最後一個營業日、集保戶 ID 歸戶、依持股分級列出各級人數、股數與占集保庫存比例。三個月趨勢可取每個曆月最後一筆已發布週資料。

同日 session POST 查詢 2330 的官方表格片段：

```text
15 1,000,001以上 1,481 21,966,711,289 84.70
16 差異數調整（說明4） -1,000 -0.00
17 合 計 3,050,518 25,932,370,067 100.00
```

初版透明定義：

- `shareholderCount`：TDCC `持股分級=17` 的 `人數`；以官方總計列為準，不自行把分級人數相加，避免歸戶／統計口徑差異。
- `largeHolderPct`：TDCC `持股分級=15` 的 `占集保庫存數比例%`；官方查詢頁定義級距15為「1,000,001以上」。級距16是「差異數調整（說明4）」不納入持股比重。
- UI 顯示正式名稱：`TDCC 高持股級距15（持股1,000,001以上）`，不宣稱複製 StatementDog 的「大股東」內部門檻。

### 2. TWSE OpenAPI 董監事持股

官方目錄與 schema：

- https://openapi.twse.com.tw/
- https://openapi.twse.com.tw/v1/swagger.json

正式 endpoint：

- 上市公司：`https://openapi.twse.com.tw/v1/opendata/t187ap11_L`
- 公開發行公司：`https://openapi.twse.com.tw/v1/opendata/t187ap11_P`

Swagger summary：

- `t187ap11_L`：上市公司董監事持股餘額明細資料
- `t187ap11_P`：公發公司董監事持股餘額明細

核心欄位：

- `出表日期`
- `資料年月`
- `公司代號`
- `職稱`
- `目前持股`
- `設質股數`
- `內部人關係人目前持股合計`

實際下載探針：

- `t187ap11_L` HTTP 200，完整下載 10,355,561 bytes，27,475 rows；含 2330 台積電 11508 資料。
- `t187ap11_P` HTTP 200，2,542,405 bytes，6,660 rows；當期資料年月 `11508`。

初版透明定義：

- `directorSupervisorShares`：按公司、資料年月，加總職稱包含 `董事長本人`、`董事本人`、`獨立董事本人`、`監察人本人` 的 `目前持股`；排除法人代表人、經理人、關係人，避免範圍混淆。
- `directorSupervisorPct`：`directorSupervisorShares / 已發行普通股數`；分母使用同日官方公司基本資料欄位。若分母或月份不一致，`unknown`。
- 12 個月比較使用相同公司、相同職稱範圍、最新資料年月與 12 個月前資料年月。

### 3. TWSE 大股東交叉參考

- `https://openapi.twse.com.tw/v1/opendata/t187ap02_L`
- Swagger summary：上市公司持股逾 10% 大股東名單。
- 可作為大股東名單的交叉研究資料；不直接替代 TDCC 股權分散趨勢。

## 政策結論

- TDCC 是官方公開 CSV，資料可取得；不再把「找不到來源」列為 blocker。
- TWSE OpenAPI 已提供董監事持股欄位；不把 TDCC `1-4` 分戶保管資料冒充完整董監持股。
- 目前唯一需要產品確認的是：是否接受我們明示的 `TDCC級距15（持股1,000,001以上）` 定義，而不是 StatementDog 未公開的內部算法。
- 本次只處理 source policy、證據與 contract；未修改 `trust`、`growth`、`lowPosition` 策略邏輯。
