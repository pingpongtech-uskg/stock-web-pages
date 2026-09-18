# 台股三策略選股

首頁是三個策略 tab：投信關注、成長改善、低位觀察。切換 tab 後才顯示該策略股票；股票列只發布同時有現在價格與祖魯合理價的已知資料。

## 策略 tab 與篩選條件

- **投信關注**：A 母體為投信十日淨買超前 100；依十日淨買超股數排序，成交占比作參考。
- **成長改善**：A 母體內三月合計營收年增至少 15%；依營收成長排序，正式營業利益成長不以營收代理取代。
- **低位觀察**：調整價四年回歸可用、`Z ≤ 0`、回歸 `slope > 0`；嚴格低基期路徑另用 `Z ≤ -1` 與品質／成長條件。

三個 tab 使用完全相同的祖魯合理價標準：

```text
保守成長率 = 三月營收年增 × 0.8
合理本益比 =（保守成長率 + 現金股利殖利率）× 100
Forward EPS = 現在價格 ÷ 目前 PE ×（1 + 保守成長率）
祖魯合理價 = Forward EPS × 合理本益比
```

祖魯法則本身是成長股選股框架，不是另一個獨立目標價公式；本網站把已知營收成長、PE、股利殖利率與現在價格代入同一個透明情境。缺任一輸入，股票不列入畫面。

## 目前範圍

- 今日研究、選股器、排行榜、個股、比較、自選與紀律、策略檢驗、方法與資料八頁。
- 四年線性回歸計算、十個市場交易日投信指標、三個月營收成長公式都有單元測試。
- FinMind client 有 token 不落前端、30 秒 timeout、最多三次嘗試、Retry-After、402/429 停止、每 run 300 次且不超過帳號剩餘 80% 的預算閘門。
- 發布器會以 yfinance `Adj Close` 補齊四年價格回歸；若 Yahoo 暫時不可用，才退回明示的 FinMind 未調整收盤代理。
- 財務品質保留嚴格三年規則，同時呈現 yfinance 最新年度淨利、營業現金流、營業利益率、ROE 與淨負債／EBITDA 代理；代理不冒稱正式通過。低基期成長／品質榜由發布器分別計算，共同要求合格價格、Z≤−1、正向 slope，投信名次只作排序。
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
FINMIND_TOKEN='(由安全注入工具提供)' python3 scripts/fetch_finmind.py --output public/data
```

上面只是介面示意；不要把真實 token 寫進 shell history、repo 或聊天。腳本只使用 `https://api.finmindtrade.com/api/v4/data`，另以 `https://api.web.finmindtrade.com/v2/user_info` 讀取配額資訊。不能取得配額時會 fail closed，不以未知額度冒險抓取。

## 資料與研究邊界

- 金融資料來源 allowlist 只有 FinMind、TWSE、TPEx、yfinance；目前發布器會用 FinMind 的法人／營收／財報資料，並用 yfinance 補齊調整後價格與最新年度財務代理。
- 公開快照會保留 yfinance 的來源標記、期間與處理版本；若 yfinance 不可用，才退回明示的 FinMind 未調整收盤代理，不能把代理誤稱為正式條件。
- 產品條件是研究規則，不是投資建議、報酬保證或已證明的護城河。50% CAGR／30% 回撤目標若資料不足，顯示 `not_evaluable`。
- 這個 base 不是完整 P5 回測認證。研究頁會明示資料與績效缺口。

目前所有策略共用 A 母體：公開投信十日買超前 100。每日先更新來源排行，再只對這 100 檔抓取與計算，避免把有限的免費資料與運算分散到全市場。每個數值保留來源、期間與口徑；研究代理候選不代表投資建議或績效。

完整產品規格見 `PLAN.md`；可用資料盤點與替代策略見 `docs/SOURCES.md`、`docs/RESEARCH_PROTOCOL.md`。
