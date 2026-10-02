# 資料契約摘要

每個發布有 `schemaVersion`、`strategyVersion`、`formulaVersion`、`runId`、`marketDate`、`generatedAt`、`sourceRefs`。每個指標保留 value、unit、period、available_at、status、source_refs 與 formula_version。

`status` 僅能是 `pass`、`fail`、`unknown`、`not_applicable`。缺值不能變成 0；financial period、幣別、報表口徑與公司行動未核對時必須標 unknown。

前端只讀 `public/data/latest.json` 與同 run 的 `stocks/<code>.json`。私人持股、筆記、交易與原始 API payload 不公開。

## Screening export v1

`public/data/screening-export.json` is the compact interchange consumed by n8n and the website history builder. A successful `daily.yml` run uploads exactly the same bytes in the `screening-export` artifact, alongside `publication.json`. The artifact is created only after the validated data commit reaches `main`. The export records the source code commit; `publication.json` records the resulting publication commit, avoiding a self-referential commit hash.

The export includes `marketDate`, `generatedAt`, `runId`, `requestId`, `actionsRunId`, `sourceGitCommit`, `revision`, `formulaVersions`, `freshness`, `coverage`, and `funnel`. `strategies` contains `trust`, `growth`, and `lowPosition` membership and rank. `selectedStocks` contains each selected code exactly once, with compact metrics, every strategy's rank/status/reason, and source provenance. Metric ratios `earningsGrowth`, `dividendYield`, and `participation10` are fractions (0.15 means 15%); PE, PEG and total-return PE are multiples. Missing metrics remain JSON null, with their provenance origin set to unavailable. Normalized financial periods come from `healthInputs`, while `growthValuation.inputAudit` supplies reported/derived/proxy origins. Regression and institutional metrics retain their own calculation periods and sources. Empty strategies are valid successful zero results; failed runs never create a successful export. `degraded` financial coverage is disclosed; stale official market dates are rejected.

`payloadHash` is SHA-256 over UTF-8 compact JSON with recursively sorted object keys, Unicode preserved, and the top-level `payloadHash` omitted. The serialized artifact puts the hash member last. Consumers should verify the exact bytes instead of serializing JSON numbers again:

```javascript
const suffix = /,"payloadHash":"([a-f0-9]{64})"}$/;
const match = raw.match(suffix);
if (!match) throw new Error('screening export hash suffix missing');
const preimage = raw.replace(suffix, '}');
const actual = crypto.createHash('sha256').update(preimage, 'utf8').digest('hex');
if (actual !== match[1]) throw new Error('screening export hash mismatch');
const screening = JSON.parse(raw);
```

The hash provides content integrity and traceability. Access permissions remain the trust boundary. `revision` is the first 12 hexadecimal characters of the same canonical body with both `revision` and `payloadHash` omitted.

Archive months keep one active record per real market date for compatibility. `revisionRefs` references immutable `/data/archive/v1/revisions/<marketDate>.<revision>.json` records with SHA-256. A correction changes the active pointer and preserves the original record. Existing six historical dates are tagged `legacy`; their original bytes remain available, and unavailable request/publication or point-in-time lineage is never invented. `formulaVersion` from old releases maps into `formulaVersions.regression`.

`trading-calendar.json` uses `trading-calendar-v1`, `timezone: Asia/Taipei`, one verified `year`, `closedDates`, `openExceptions`, `sourceUrl`, and `fetchedAt`. It derives only from the TWSE exchange holiday schedule. Weekends are closed unless explicitly open; a missing or different year's calendar fails closed. Exchange-open rows in the holiday API are exceptions, not holidays.
