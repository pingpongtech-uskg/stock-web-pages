# stock-web-pages — Scripts

這個網頁專案會用到的主要 scripts，集中在這裡統一管理。

## 目錄結構

```
scripts/
├── README.md                        ← 這份文件
├── build_site_data.py               ← 將 batch_*.json 轉換為 per-stock JSON（含技術指標）
├── build_summary.py                 ← 生成列表頁用的 stocks_summary.json
└── test_build_site_data.py          ← build_site_data.py 的 pytest 測試
```

## 管線流程（Pipeline）

```
┌─────────────────────────────────────────────────────────┐
│  1. screener/daily_trust_monitor.py                     │
│     (cronjob 每交易日 20:30 執行於 /root/tw-stock-monitor)  │
│     → 產出 /tmp/tw_stock_data/batch_*.json               │
├─────────────────────────────────────────────────────────┤
│  2. scripts/build_site_data.py                          │
│     → 讀取 batch_*.json                                  │
│     → 計算 MA / RSI / KD / MACD 技術指標                  │
│     → 產出 public/data/stocks/{code}.json (每個股票一個檔)  │
├─────────────────────────────────────────────────────────┤
│  3. scripts/build_summary.py                            │
│     → 讀取 public/data/stocks/*.json                     │
│     → 產出 public/data/stocks_summary.json               │
├─────────────────────────────────────────────────────────┤
│  4. npm run build (Astro)                               │
│     → 讀取 stocks_summary.json                          │
│     → 建置靜態網站到 dist/                                │
├─────────────────────────────────────────────────────────┤
│  5. GitHub Actions (.github/workflows/deploy.yml)       │
│     → 部署 dist/ 到 GitHub Pages                        │
└─────────────────────────────────────────────────────────┘
```

## 備份狀態

- **screener/** — 所有篩選/回測 Python scripts 已從 `/root/tw-stock-monitor` 完整備份到這裡
- **scripts/** — 網頁資料管線 scripts（新建）
- 兩邊都已 commit 進 git，push 到 GitHub

## 注意事項

- MA 計算規則：`data[T-N:T]` **不含 T**（使用者的 hard rule）
- `build_site_data.py` 輸入路徑：`/tmp/tw_stock_data/batch_*.json`
- 輸出目錄：`public/data/stocks/` 和 `public/data/stocks_summary.json`
