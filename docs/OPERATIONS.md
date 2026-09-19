# 運作說明

## FinMind 請求邊界

- 每次 run 先以 `user_info` 讀取帳號配額；有效嘗試數為 `min(300, floor(剩餘配額 × 0.8))`，user_info 本身的 HTTP attempt 也計入 run。
- 每個請求 timeout 30 秒，最多 3 次嘗試；順序執行（concurrency 1，低於規格上限 2），請求間保留間隔。
- 402 或 429 立即停止 FinMind 補資料，保存待補 queue，不換 token、不繞過限制。
- Authorization header 只在 server-side／CI；token 不進 `public/`、瀏覽器 network、log、Git 或 acceptance report。

## 部署啟用

Cloudflare workflow 預設不執行部署，避免未設定 secrets 時製造假失敗。設定 repository variable `CLOUDFLARE_PAGES_ENABLED=true` 後，才會讀取 `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`、`CLOUDFLARE_PAGES_PROJECT` 三個 Actions secrets。

```bash
FINMIND_TOKEN='由安全注入工具提供' python3 scripts/fetch_finmind.py \
  --codes 2330,2454,2303,2317,2382,2881,3034,3711 \
  --output public/data
python3 scripts/refresh_snapshot.py --output public/data
python3 scripts/verify_snapshot.py
```

`fetch_finmind.py` 是 seed 階段；不可把它的中間輸出直接部署。`refresh_snapshot.py` 產生 3.5 年 release，`verify_snapshot.py` 必須通過才可 build/deploy。若要從 Infisical 使用，先由外部安全注入步驟取得 `Finmind_1`，再以 process environment 傳給腳本；不要把 token 寫入 `.env` 或命令列字面值。GitHub Actions 用 `FINMIND_TOKEN` secret，不能在 PR workflow 暴露。

## 發布一致性

腳本先寫 `releases/<run_id>/stocks/` 與 `manifest.json`，最後才原子替換 `latest.json`。舊 release 不覆蓋。前端先載入 latest，再以同一 run_id 讀個股資料；版本不符就拒絕顯示。

## 失敗／恢復

- 核心母體或來源失敗，不清空上一個可用發布。
- 個股補資料失敗可生成降級快照，但該檔狀態為 `unknown`，不進正式進場觀察。
- `private/refresh_queue.json` 是待補工作檔，不得部署到 Pages。
- 部署仍需另外檢查公開用途與來源授權；API 取得資格不等於再散布權。
