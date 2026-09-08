# 資料契約摘要

每個發布有 `schemaVersion`、`strategyVersion`、`formulaVersion`、`runId`、`marketDate`、`generatedAt`、`sourceRefs`。每個指標保留 value、unit、period、available_at、status、source_refs 與 formula_version。

`status` 僅能是 `pass`、`fail`、`unknown`、`not_applicable`。缺值不能變成 0；financial period、幣別、報表口徑與公司行動未核對時必須標 unknown。

前端只讀 `public/data/latest.json` 與同 run 的 `stocks/<code>.json`。私人持股、筆記、交易與原始 API payload 不公開。
