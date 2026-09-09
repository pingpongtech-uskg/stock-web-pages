# 台股低位研究室

以「為什麼值得研究」與「還缺哪些條件」為核心的台股研究工作台。這個 repo 是依產品計畫建立的可執行 base：React + TypeScript + Vite 前端，FinMind 只在離線資料產生器／CI 使用，瀏覽器只讀同一次發布的靜態快照。

## 目前範圍

- 今日研究、選股器、排行榜、個股、比較、自選與紀律、策略檢驗、方法與資料八頁。
- 四年線性回歸計算、十個市場交易日投信指標、三個月營收成長公式都有單元測試。
- FinMind client 有 token 不落前端、30 秒 timeout、最多三次嘗試、Retry-After、402/429 停止、每 run 300 次且不超過帳號剩餘 80% 的預算閘門。
- 發布器會以 yfinance `Adj Close` 補齊四年價格回歸；若 Yahoo 暫時不可用，才退回明示的 FinMind 未調整收盤代理。
- 財務品質保留嚴格三年規則，同時呈現 yfinance 最新年度淨利、營業現金流、營業利益率、ROE 與淨負債／EBITDA 代理；代理不冒稱正式通過。
- 成長榜使用可重現的三月合計營收年增（門檻 15%）作為營收代理；投信榜使用十個市場交易日淨買超與成交占比；嚴格進場條件仍可為零，但研究榜不會因缺一個條件而清空。
- 自選／筆記／交易紀錄留在瀏覽器本機 IndexedDB；匯出檔由使用者自己保存，不做雲端同步。

## 啟動

```bash
npm install
npm run test:unit
npm run typecheck
npm run build
npm run dev
```

打開 `http://localhost:5173`。若尚未生成 `public/data/latest.json`，網站會顯示資料不可用狀態，不會偷偷塞示範股票。

## 生成 FinMind 快照

正式執行時把 token 放在執行環境或 GitHub Actions secret `FINMIND_TOKEN`。本機可從 Infisical 取值後，以記憶體環境變數傳給腳本；token 不寫入檔案、前端或 log：

```bash
FINMIND_TOKEN='(由安全注入工具提供)' python3 scripts/fetch_finmind.py --codes 2330,2454,2303,2317,2382,2881,3034,3711 --output public/data
```

上面只是介面示意；不要把真實 token 寫進 shell history、repo 或聊天。腳本只使用 `https://api.finmindtrade.com/api/v4/data`，另以 `https://api.web.finmindtrade.com/v2/user_info` 讀取配額資訊。不能取得配額時會 fail closed，不以未知額度冒險抓取。

## 資料與研究邊界

- 金融資料來源 allowlist 只有 FinMind、TWSE、TPEx、yfinance；目前 live seed 只會呼叫 FinMind，其他 adapter 尚未接線。
- yfinance 只允許私有交叉核對；不得把未確認公開用途的 Yahoo 序列打包進 `dist/`。
- 產品條件是研究規則，不是投資建議、報酬保證或已證明的護城河。50% CAGR／30% 回撤目標若資料不足，顯示 `not_evaluable`。
- 這個 base 不是完整 P5 回測認證。研究頁會明示資料與績效缺口。

目前發布範圍是設定檔中的 8 檔追蹤標的，不宣稱掃描全市場 3,147 檔。每個數值保留來源、期間與口徑；研究代理候選不代表投資建議或績效。

完整產品規格見 `PLAN.md`；可用資料盤點與替代策略見 `docs/SOURCES.md`、`docs/RESEARCH_PROTOCOL.md`。
