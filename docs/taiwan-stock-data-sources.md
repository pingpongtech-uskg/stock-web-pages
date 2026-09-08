# Taiwan Public Data Sources

## Source priority

1. TWSE OpenAPI: https://openapi.twse.com.tw/v1/swagger.json
2. TPEx OpenAPI: https://www.tpex.org.tw/openapi/swagger.json
3. MOPS: https://mops.twse.com.tw/
4. TDCC: https://openapi.tdcc.com.tw/tdcc-opendata-api-docs
5. FinMind: https://api.finmindtrade.com/api/v4/data — optional free-tier fallback
6. yfinance — optional free-tier fallback for price/dividend/financial fields

Official values remain primary. A secondary provider never overwrites an
official value. Conflicts retain both values and block a definitive criterion.

## Official endpoint map

| Family | Production purpose | Endpoint examples | Notes |
|---|---|---|---|
| TWSE | listed universe, monthly revenue, quarterly income/balance, dividends, current/history valuation, prices | `openapi.twse.com.tw/v1/opendata/t187ap03_L`, `t187ap05_L`, `t187ap06_L_ci`, `t187ap07_L_ci`, `t187ap45_L`; `exchangeReport/BWIBBU_ALL`, `BWIBBU_d`, `STOCK_DAY` | market date and response schema validated |
| TPEx | OTC universe, monthly revenue, quarterly income/balance, valuation | `www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O`, `...05_O`, `...06_O_ci`, `...07_O_ci`, `tpex_mainboard_peratio_analysis` | market date and response schema validated |
| MOPS | historical annual/quarterly statements, monthly revenue, dividends, insider holdings | `ajax_t164sb03`, `ajax_t164sb04`, `ajax_t164sb05`, `ajax_t05st10_ifrs`, `ajax_stapap1` | historical requests use explicit ROC year/quarter/month and period marker |
| TDCC | shareholder count and holding distribution | `/v1/opendata/2-22`, `/v1/opendata/2-23`, dataset 11452, `qryStock` | weekly query normalized to month; fresh in-memory session per date |

## Free fallback policy

FinMind and yfinance are allowed but not required for the first official-only
release. Each request requires:

```text
budget preflight
one-code schema smoke
request/status ledger
provider provenance
official cross-check
```

HTTP 402/403/429, ban, quota exhaustion, schema drift, or missing permission
blocks the fallback. No blind retry. No credential/token is written to source,
manifest, logs, or output.

## Raw data and manifests

Raw responses live outside the source repository in a restricted evidence/cache
directory. A normalized fact stores the raw response hash, source URL, fetch
metadata, period, unit, parser version, formula version, and announcement date.
Production runner accepts only `manifest.json` with:

```json
{
  "status": "complete",
  "schema_version": 1,
  "universe_complete": true,
  "files": ["records.json"],
  "hashes": {"records.json": "sha256:<64 hex>"}
}
```

An incomplete/missing/hash-mismatched manifest is a run error, not an empty
successful result.

## StatementDog boundary

StatementDog pages, API responses, cookies, and sessions are never production
sources. External labels may be supplied separately to the grader for manual
calibration only.
