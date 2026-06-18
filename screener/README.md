# 投信初建倉 Screener

台股投信買超篩選系統 — 每日自動抓取 TWSE/TPEx 投信買賣超資料，進行基本面評分、回歸線篩選、排名輸出。

## 核心腳本

| 檔案 | 用途 |
|------|------|
| `daily_trust_monitor.py` | **每日篩選主程式** — cronjob 每天執行 |
| `fundamental_scorer.py` | 基本面評分（成長 G、地雷 L、股息、估價） |
| `chip_scorer.py` | 籌碼面評分（法人買賣、融資券、股權集中度） |
| `build_trust_cache.py` | 建置投信買賣超歷史快取 |
| `data_loader.py` | FinMind API + yfinance 資料載入 |

## 回測

| 檔案 | 用途 |
|------|------|
| `backtest_main.py` | 主回測框架 |
| `backtest_trust_rank.py` | 投信排名策略回测 |
| `backtest_trust_fundamental.py` | 投信+基本面策略回测 |
| `backtest_weekly_lei.py` | 雷老闆週線法回测 |
| `ten_year_backtest.py` | 10年全策略回测 |

## 資料目錄（不在此 repo 內）

- `data/` — batch JSON（OHLCV 歷史，~240MB）
- `output/` — 快取 + 報告（~279MB）
- `output/reports/daily_trust10_*.json` — 每日篩選結果

## 執行方式

```bash
cd tw-stock-monitor
python3 daily_trust_monitor.py
```
