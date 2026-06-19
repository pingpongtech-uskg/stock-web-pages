# stock-web-pages — Scripts

這個網頁專案的主要 scripts，集中在這裡統一管理。

## 目錄結構

```
scripts/
├── README.md                        ← 這份文件
├── update_site.sh                   ← 一鍵更新：重建資料 + build Astro
├── build_screener_history.py        ← 合併 daily_trust10_*.json → screener_history.json
├── build_site_data.py               ← 將 batch_*.json 轉換為 per-stock JSON（含技術指標）
├── build_summary.py                 ← 生成列表頁用的 stocks_summary.json
└── test_build_site_data.py          ← build_site_data.py 的 pytest 測試
```

## 管線流程（Pipeline）

```
┌─────────────────────────────────────────────────────────────┐
│  1. Cronjob: 法人初建倉每日監控 (平日 20:30 台灣時間)           │
│     → /root/tw-stock-monitor 產出 daily_trust10_YYYYMMDD.json │
├─────────────────────────────────────────────────────────────┤
│  2. scripts/build_screener_history.py                        │
│     → 讀取所有 daily_trust10_*.json                           │
│     → Active: 去重複，取每檔最新上榜資料，按日期排序              │
│     → Archive: 所有歷史紀錄，按日期分組，可折疊展開               │
│     → 產出 src/data/screener_history.json                    │
├─────────────────────────────────────────────────────────────┤
│  3. npm run build (Astro)                                    │
│     → 讀取 screener_history.json                             │
│     → 渲染 ScreeningRow 組件（玻璃擬態表格列）                   │
│     → 建置靜態網站到 dist/                                    │
├─────────────────────────────────────────────────────────────┤
│  4. GitHub Actions (.github/workflows/deploy.yml)            │
│     → push dist/ 到 gh-pages branch                          │
│     → 部署到 https://pingpongtech-uskg.github.io/stock-web-pages/ │
└─────────────────────────────────────────────────────────────┘
```

## 快速更新

```bash
# 有新的 daily_trust10_*.json 後，一鍵更新
cd /root/stock-web-pages
bash scripts/update_site.sh
git add . && git commit -m "update: screening results" && git push
```

## 資料格式

### screener_history.json
```json
{
  "active": [
    {
      "code": "2105",
      "name_zh": "正新",
      "name_en": "Cheng Shin...",
      "net_amount_10d": 2556344928,
      "net_shares_10d_zhang": 86217,
      "last_date": "2026-06-18",
      "cur_price": 29.65,
      "g_score": 100,
      "l_score": 100,
      "regression_z": -1.27,
      "rank": 36,
      "screening_date": "2026-06-18"
    }
  ],
  "archive": {
    "2026-06-18": [...],
    "2026-06-17": [...]
  }
}
```

## 網頁欄位說明

| 欄位 | 來源 | 說明 |
|------|------|------|
| 代號/名稱 | code / name_zh | 股票代碼與中文簡稱 |
| 投信10日買超 | net_amount_10d | 10日投信買超金額（億/萬） |
| 投信10日買超張數 | net_shares_10d_zhang | 10日投信買超張數 |
| 上榜日 | last_date | 最後一次出現在篩選清單的日期 |
| 成長 | g_score | 成長性評分（金≥80 銀≥60 銅<60） |
| 地雷 | l_score | 地雷股評分（金≥80 銀≥60 銅<60） |
| 便宜 | — | 暫為 placeholder |
| 定存 | — | 暫為 placeholder |
| 股價 | cur_price | 當日收盤價 |
| Z | regression_z | 線性回歸 Z-score |

## Active / Archive 邏輯

- **Active**: 近 30 天內有上榜紀錄的股票，取最新一筆，以上榜日排序（越新越前面）
- **Archive**: 所有歷史篩選結果，按日期分組（越新越前面），每個日期區塊可折疊展開
