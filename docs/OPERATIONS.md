# 運作說明

## FinMind 請求邊界

- 每個台北曆日，專案累計最多 300 次 FinMind HTTP attempts，包含 `user_info`、重試與所有同日重跑；持久化計數不會因新 run 歸零。每次先以 `user_info` 查核實際帳戶配額，同一已觀測配額視窗只使用剩餘配額的 80%，並受當日尚未使用的專案額度限制。只有實際配額查詢確認帳戶用量下降，才可重建配額視窗 allowance；專案當日累計仍不歸零。
- 每個請求 timeout 30 秒，最多 3 次嘗試；順序執行（concurrency 1，低於規格上限 2），請求間保留間隔。
- 402 或 429 立即停止 FinMind 補資料，保存待補 queue，不換 token、不繞過限制。
- Authorization header 只在 server-side／CI；token 不進 `public/`、瀏覽器 network、log、Git 或 acceptance report。

## 部署啟用

正式部署沿用現有 Cloudflare Pages 的 `main` Git integration。`daily.yml` 將通過驗證的資料推送到 `main`，Cloudflare 從已接上的分支建置及發布；n8n 再讀取正式網站，核對相同的 run、payload hash 與來源 commit，通過後才記 deploy verified。

Cloudflare Pages 的 `main` Git integration 是唯一正式發布路徑。舊 Direct Upload workflow 已移除；不需要 `CLOUDFLARE_PAGES_ENABLED` 或該舊 workflow 的 Direct Upload secrets。程式更新與已驗證資料更新都經 `main`，並以正式網站內容核對作為發布驗收。

```bash
python3 scripts/refresh_snapshot.py --as-of YYYY-MM-DD --output public/data
python3 scripts/fetch_finmind.py --supplement --output public/data --cache-dir .cache/finmind \
  --budget-date YYYY-MM-DD --as-of YYYY-MM-DD
python3 scripts/refresh_snapshot.py --recompute-existing --as-of YYYY-MM-DD --output public/data
python3 scripts/verify_snapshot.py
```

FinMind supplements an already fetched official public snapshot; it does not seed or replace the tracked universe. Inject `FINMIND_TOKEN` through process environment or the GitHub Actions secret. Never write its value into command-line arguments, `.env`, browser assets, or PR workflow logs. Intermediary files are not publishable until snapshot, freshness, history, and build gates pass.

## 發布一致性

腳本先寫 `releases/<run_id>/stocks/` 與 `manifest.json`，最後才原子替換 `latest.json`。舊 release 不覆蓋。前端先載入 latest，再以同一 run_id 讀個股資料；版本不符就拒絕顯示。

## 失敗／恢復

- 核心母體或來源失敗，不清空上一個可用發布。
- 個股補資料失敗可生成降級快照，但該檔狀態為 `unknown`，不進正式進場觀察。
- `private/refresh_queue.json` 是待補工作檔，不得部署到 Pages。
- 部署仍需另外檢查公開用途與來源授權；API 取得資格不等於再散布權。

## n8n daily release and recovery

n8n owns the Monday–Friday 18:00 Asia/Taipei trigger. It verifies the authoritative TWSE trading calendar before requesting a trading session. The target completion is 18:45; 19:30 is the overdue deadline. These are operational targets, not a guaranteed API SLA. A holiday creates a skipped ledger entry rather than a zero-stock screening result.

Dispatch `.github/workflows/daily.yml` on `main` with required `request_id` and independently determined `market_date` (`YYYY-MM-DD`). The Actions run name includes both fields. Resolve the exact run by the request ID and verify the exported request ID, Actions run ID, market date, hash, and publication commit before writing to Notion. The workflow serializes production refreshes with `concurrency: daily-snapshot` and never cancels a running writer.

The pipeline fetches official public bulk sources first even when a FinMind token exists. It verifies the requested date against the newly fetched official universe before the expensive refresh. It then supplements only financial gaps and recomputes existing inputs without another network refresh:

```bash
python scripts/fetch_finmind.py --supplement --output public/data \
  --cache-dir .cache/finmind --budget-date YYYY-MM-DD --as-of YYYY-MM-DD \
  --max-requests 300 --max-runtime-seconds 1500
python scripts/refresh_snapshot.py --recompute-existing --as-of YYYY-MM-DD --output public/data
```

The free project budget is a durable maximum of 300 HTTP attempts per Taipei calendar day across every run and retry, including quota-query attempts. Supplementary requests also stay within 80% of the actually observed remaining account quota. A verified account quota-window reset may restore its allowance, but never resets the project daily counter. Missing token, unknown quota, 402/429, timeout, and budget exhaustion stop supplementation; they do not purchase access or reset usage. `.cache/finmind/state.json` and `rows.json` contain the daily checkpoint and durable history. Always-save Actions cache keys include Taipei budget date, run ID, and attempt. Restore first uses the same-day prefix, then older historical rows. Before making new requests, the workflow also restores same-day failure artifacts and conservatively merges maximum consumed attempts, minimum budget ceilings, block state, and retry delays. Failure artifacts preserve checkpoint evidence for recovery; never delete the same-day usage state to retry. A retry must retain both consumed attempts and queued gaps.

Stages have explicit limits, including at most 25 minutes for supplementary requests. The 80-minute total timeout fits the 18:00–19:30 window with limited headroom; source delays may still miss the 18:45 target. Record actual run duration, request count, cache hits, remaining budget, gaps, and missed deadline. Initial cold historical population can remain degraded and is not evidence of complete valuation coverage.

A successful release publishes the canonical export and archive together. Only then does Actions upload `screening-export` containing `screening-export.json` and `publication.json`, plus `validated-static-release`. On failure, preserve the previous production release and checkpoint; classify the ledger as failed and keep the exact Actions URL and error. Notion retry resumes the same validated export instead of fetching data again. CAS coordination on the dedicated state branch is required for concurrent n8n executions; a lookup followed by a create is not an atomic lock.

To verify a deployed candidate, use `scripts/verify_history_production.py --base-url <production-url> --expected-dir public/data`. The verifier compares exact latest/index/month/export content, all active date revision references, SHA-256, and cache headers. An Actions success alone does not prove Cloudflare deployment or Notion acceptance. If deployment or Notion verification fails, retain the validated artifact and report the failing stage without inserting a zero result.

## Legacy archive backfill

Backfill uses only the six retained real market dates: 2026-09-08, 2026-09-11, 2026-09-18, 2026-09-23, 2026-09-24, and 2026-10-01. Pin the repository commit, verify the index, month SHA-256 and active immutable revision, then archive the recorded selections without another screening or API fetch. Preserve each original generatedAt and available metrics. Mark all six as legacy_archive; unknown formula versions, financial input provenance, original request IDs and Actions lineage remain unavailable. Archive corrections preserve the earlier revision rather than replacing its evidence.

Free FinMind supplementation may leave partial financial coverage. Report the selected count, complete valuation input count, missing-input reasons and remaining queue separately. A successful validated screening can still be degraded; a missing input never becomes zero, pass, or a fabricated historical value.
