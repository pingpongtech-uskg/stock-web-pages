# Stock Web Pages — Astro 股票視覺化網站實作計畫

> **For Planner:** Decompose this into bite-sized kanban tasks assigned to pro-worker/worker/reviewer.
> **目標:** 建立 Fugle 風格的台灣股票圖卡網站，部署到 GitHub Pages
> **架構:** Astro SSG + ECharts 互動圖表 + 預計算 JSON 資料層（零後端）
> **部署:** GitHub Pages (`pingpongtech-uskg/stock-web-pages`)

---

## 優先級（依使用者要求）
1. **美觀** — Fugle 風格，現代化 UI，深色/淺色主題
2. **資訊正確度** — 資料計算必須準確，不可有誤
3. **資訊豐富度** — 越接近 Fugle 越好

---

## 架構總覽

```
stock-web-pages/
├── data/                              # Python 資料管線
│   ├── build_site_data.py             # batch_*.json → per-stock JSON
│   └── build_diagnosis_cache.py       # FinMind → 22 健診指標（Phase 2）
├── public/data/stocks/                # 生成資料
│   └── {code}.json
├── src/
│   ├── pages/
│   │   ├── index.astro                # 股票列表頁
│   │   └── [code].astro               # 股票明細頁
│   ├── components/
│   │   ├── StockCard.astro            # 列表卡片
│   │   ├── PriceChart.astro           # ECharts 價格走勢
│   │   ├── VolumeChart.astro          # ECharts 成交量
│   │   ├── DiagnosisCards.astro       # 4 健診分數卡（Phase 2）
│   │   ├── DiagnosisDetail.astro      # 展開式 checklist（Phase 2）
│   │   └── Layout.astro               # 頁面框架
│   └── styles/
│       └── global.css
├── astro.config.mjs
├── package.json
└── .github/workflows/deploy.yml
```

## 資料流

```
/tmp/tw_stock_data/batch_*.json  (25 files, ~2400 stocks)
        │
        ▼
  build_site_data.py
        │  計算：MA5/10/20/60, RSI14, MACD, KD, 漲跌幅
        │  輸出：public/data/stocks/{code}.json
        ▼
  Astro build (import.meta.glob)
        │
        ▼
  靜態 HTML (GitHub Pages)
```

## Phase 1 任務分解（價格圖卡，0 新 API）

### Task 1: 價格資料管線 (`build_site_data.py`)

**目標:** 從 batch_*.json 轉換為 per-stock JSON，加入技術指標

**輸入:** `/tmp/tw_stock_data/batch_*.json`
**輸出:** `public/data/stocks/{code}.json`

**Per-stock JSON 格式:**
```json
{
  "code": "2330",
  "name": "台積電",
  "start": "2000-01-04",
  "end": "2026-05-22",
  "days": 6559,
  "price": {
    "dates": ["2025-01-02", ...],
    "close": [1080, 1095, ...],
    "volume": [25000000000, ...],
    "ma5": [null, null, null, null, 1082.0, ...],
    "ma20": [...],
    "ma60": [...],
    "rsi14": [...],
    "kd_k": [...],
    "kd_d": [...],
    "macd": [...],
    "macd_signal": [...],
    "macd_hist": [...]
  },
  "latest": { "price": 980, "change_pct": 1.5, "volume": 25e9 },
  "change": { "1d": 1.5, "1w": -2.3, "1m": 5.1, "3m": 12.0, "1y": 35.0 },
  "ma_status": "多頭排列"
}
```

**技術指標公式:**
- MA(N): N 日簡單移動平均（不含當日）
- RSI(14): `100 - (100 / (1 + avg_gain_14 / avg_loss_14))`
- KD(9,3): RSV → K/D 平滑
- MACD(12,26,9): EMA12 - EMA26 → signal → histogram
- 漲跌幅: `(today_close - N_days_ago_close) / N_days_ago_close * 100`
- MA 排列: 比對 MA5/10/20/60 順序

**注意:** MA 計算用 `data[T-N:T]` 不含 T（使用者規範）。只取最近 500 個交易日以控制檔案大小。

---

### Task 2: Astro 專案初始化

**目標:** 建立 Astro 專案 + ECharts + GitHub Pages 部署設定

**步驟:**
1. `npm create astro@latest` 在 `/root/stock-web-pages/`（選 Empty, TypeScript strict）
2. 安裝依賴: `echarts`, `echarts-for-react`（或用 vanilla echarts）
3. 設定 `astro.config.mjs`：`site: 'https://pingpongtech-uskg.github.io'`, `base: '/stock-web-pages/'`
4. 設定 `.github/workflows/deploy.yml`：GitHub Actions → GitHub Pages
5. 建立 `.gitignore`（排除 node_modules, public/data/stocks/）

**GitHub Pages 部署設定:**
- Source: GitHub Actions
- Build: `npm install && npm run build`
- Output: `dist/`

---

### Task 3: 股票列表頁 (`index.astro`)

**目標:** 卡片瀑布流，每張卡片顯示 sparkline + 基本指標

**卡片內容:**
- 股票代碼 + 名稱（`2330 台積電`）
- SVG sparkline（最近 60 日收盤價迷你走勢）
- 最新價格 + 漲跌幅（紅漲綠跌）
- MA 排列指示燈（多頭🟢/空頭🔴/盤整🟡）
- 成交量狀態（量增/量縮）

**互動:** 點擊卡片 → 進入 `/{code}` 明細頁

**樣式:**
- 3 欄網格（桌面）/ 2 欄（平板）/ 1 欄（手機）
- 卡片 hover 效果（微幅上浮 + 陰影）
- Fugle 風格配色：白色卡片 + 淡灰邊框 + 圓角 12px

---

### Task 4: 股票明細頁 (`[code].astro`)

**目標:** 完整互動圖表頁面

**區塊:**
1. **標題區:** 股票代碼 + 名稱 + 最新價格 + 漲跌幅
2. **走勢圖:** ECharts 收盤價折線圖 + MA5/20/60 疊圖
   - Tooltip 顯示日期/價格/MA 值
   - 縮放/拖曳
   - 時間切換按鈕（1月/3月/6月/1年/全部）
3. **成交量圖:** ECharts 柱狀圖，紅漲綠跌
4. **技術指標區:** RSI + MACD + KD 切換頁籤
5. **漲跌幅表:** 日/週/月/季/年 報酬率

**ECharts 使用方式:**
- 用 vanilla echarts（不依賴 React）
- `<script>` tag 在 Astro page 內初始化
- 圖表資料從 JSON 讀取後直接注入 chart option

---

### Task 5: 全域樣式設計

**目標:** Fugle 風格的現代化 UI

**設計系統:**
- 字體: system-ui, -apple-system, sans-serif
- 主色: #1a73e8（藍，漲）/ #ea4335（紅，跌）
- 背景: #f5f5f5（淺灰）/ #1a1a2e（深色主題）
- 卡片: 白色 bg, border-radius 12px, box-shadow
- 間距: 8px grid system
- RWD 斷點: 640px / 1024px / 1280px

**深色主題支援:**
- CSS `prefers-color-scheme: dark` 自動切換
- 或用 class toggle 手動切換

---

### Task 6: GitHub Pages 部署

**目標:** 自動部署到 GitHub Pages，生成公開網址

**GitHub Actions workflow:**
```yaml
name: Deploy to GitHub Pages
on:
  push:
    branches: [main]
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-pages-artifact@v3
        with:
          path: dist/
  deploy:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    steps:
      - uses: actions/deploy-pages@v4
```

**部署後網址:** `https://pingpongtech-uskg.github.io/stock-web-pages/`

---

## Phase 2（後續，需 FinMind）

### Task 7: 健診快取 (`build_diagnosis_cache.py`)
- 從 FinMind API 拉取財報/營收/股利/現金流
- 計算 22 指標 pass/fail
- 重複利用 `fundamental_scorer.py` 的 FinMind 封裝層

### Task 8: 健診卡片元件
- `DiagnosisCards.astro`：4 個分數卡（便宜股/成長股/定存股/地雷股）
- `DiagnosisDetail.astro`：點擊展開 checklist（22 項 pass/fail）

---

## 🔧 環境資訊

- **Repo:** `pingpongtech-uskg/stock-web-pages` (empty, main branch)
- **Local path:** `/root/stock-web-pages/`
- **Git auth:** GIT_ASKPASS=/usr/local/bin/hermes-stock-askpass.sh (GITHUB_TOKEN_STOCK from Infisical)
- **Remote:** `https://token@github.com/pingpongtech-uskg/stock-web-pages.git`
- **Price data:** `/tmp/tw_stock_data/batch_*.json` (25 files, ~2400 stocks, close+volume only)
- **Node.js:** v22.22.2
- **VPS:** Hostinger KVM2, Ubuntu 24.04
- **GitHub Pages:** 需在 repo Settings → Pages → Source: GitHub Actions

## ⚠️ 注意事項

1. **MA 計算:** `data[T-N:T]` 不含 T 日（使用者強制規範）
2. **Git 推送:** 使用 GIT_ASKPASS，絕不將 token 寫入命令
3. **資料檔案大小:** 只輸出最近 500 個交易日以控制 JSON 大小
4. **GitHub Pages base path:** `/stock-web-pages/` 必須在所有 URL 前綴
5. **ECharts:** 用 vanilla JS，不用 React wrapper（減少依賴）
6. **Commit:** 每個 task 完成後立即 commit + push
