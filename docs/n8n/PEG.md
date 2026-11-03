# PEG calculation and source recovery

The primary PEG uses reported quarterly EPS, never revenue or net-income growth as a substitute:

`PEG = PE / (100 * (latest-four-quarter EPS / preceding-four-quarter EPS - 1))`

Eight consecutive comparable quarters, a positive EPS base and positive growth are required. Same-day raw close is required. A same-day reported PE is used when consistent with EPS; otherwise the calculation records its derived PE origin. Corporate-action and EPS-basis guards remain in force. Basic and diluted EPS must not be mixed.

Every stock has `pegReview`: `available`, `needs_review`, or `not_applicable`, with reasons and periods. Unavailable PEGs are omitted from PEG ranking while retaining the stock and other metrics. The main page exposes the review list; `data/peg-review.json` contains the repair-run audit.

## Source recovery

No AI or model is used. The n8n discovery draft searches SearXNG first and uses Brave only after an unusable result or provider failure. Brave is capped at 20 calls per market date. Approved issuer domains come from TWSE/TPEx company directories. Search snippets are discovery hints, never EPS evidence.

The draft requires the owner's SearXNG service URL. With the URL unset it returns `configuration_required`, makes no provider calls, and remains unpublished. It is not yet connected to the daily workflow. Generate its auditable graph with `node scripts/n8n/build-peg-source-workflow.cjs`. Credentials remain in n8n; no keys belong in source files.

Candidate documents are bounded, cached and fetched through DNS-pinned HTTPS. The parser accepts explicit historical quarterly EPS only when issuer identity, reporting currency, scope and period can be established. It does not infer forecasts, subtract ambiguous cumulative values, or silently resolve conflicting bases. Source URL, row, document hash and observation/publication date are retained. Unresolved records stay in review.

## Repair dispatch

The manual `peg.yml` workflow accepts an exact current `market_date`, unique `request_id`, and optional `search_manifest_commit`. The manifest at `config/peg_search_results.json` has `{marketDate, stocks: [{code, name, legalName, officialDomains, results: [{url, title, provider}]}]}`. An empty manifest recomputes existing evidence without source calls.

The repair retains the exact 100-stock universe, uses the shared daily publication concurrency group, validates the canonical export and fingerprint, and publishes data with the existing compare-and-swap script. Read the exact Actions run and public release after dispatch; a 204 dispatch receipt alone does not prove publication. Do not blindly repeat an ambiguous dispatch.

The original Stockscreener workflow was backed up inactive before this migration. Its original schedules and durable ledger are preserved.
