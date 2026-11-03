# PEG calculation and source recovery

The primary PEG uses reported quarterly EPS, never revenue or net-income growth as a substitute:

`PEG = PE / (100 * (latest-four-quarter EPS / preceding-four-quarter EPS - 1))`

Eight consecutive comparable quarters, a positive EPS base and positive growth are required. Same-day raw close is required. A same-day reported PE is used when consistent with EPS; otherwise the calculation records its derived PE origin. Corporate-action and EPS-basis guards remain in force. Basic and diluted EPS must not be mixed.

Every stock has `pegReview`: `available`, `needs_review`, or `not_applicable`, with reasons and periods. Unavailable PEGs are omitted from PEG ranking while retaining the stock and other metrics. The main page exposes the review list; `data/peg-review.json` contains the repair-run audit.

## Source recovery

No AI or model is used. The n8n discovery workflow searches SearXNG first and uses Brave only after an unusable result or provider failure. Brave is capped at 20 calls per market date. Approved issuer domains come from TWSE/TPEx company directories. Search snippets are discovery hints, never EPS evidence.

The private SearXNG address is read from the singleton `searx_url` column in n8n's `Stockscreener PEG source progress` table. It is not embedded in the checked-in graph. Only explicit private HTTP(S) service addresses are accepted for SearXNG; discovered financial documents still require public HTTPS. A missing address returns `configuration_required` before provider calls. Switching n8n to a private address does not disable an existing public reverse-proxy route; remove that route in the deployment platform separately. Credentials remain in n8n; no keys belong in source files.

Generate the auditable child graph with `node scripts/n8n/build-peg-source-workflow.cjs`. `peg-parent-hook.cjs` exports `applyHook` to attach the child after the parent's verified publication outcome. It preserves the original result, schedules, credentials and ledger. The child runs asynchronously and an auxiliary failure does not fail the parent.

The dedicated progress table uses singleton row 1, a revision compare-and-swap and a 30-minute lease. Brave quota is reserved before search; an expired unrefunded reservation is counted as spent. Source results and dispatch intent survive retries. A deterministic request ID `peg-<marketDate>-ttm-v1` prevents repeating an accepted or ambiguous dispatch. Existing Actions requests are reconciled rather than dispatched again. The public latest artifact's market date drives the run; the calendar date never substitutes for an unavailable session.

Brave requests explicitly send `Accept: application/json`. Configuration/authentication errors stop that provider for the rest of the batch; rate limits and temporary failures use a cooldown. Search targets the last disclosed EPS quarter when provided, not an assumed newly completed quarter.

Candidate documents are bounded, cached and fetched through DNS-pinned HTTPS. The parser accepts explicit historical quarterly EPS only when issuer identity, reporting currency, scope and period can be established. It does not infer forecasts, subtract ambiguous cumulative values, or silently resolve conflicting bases. Source URL, row, document hash and observation/publication date are retained. Unresolved records stay in review.

## Repair dispatch

The manual `peg.yml` workflow accepts an exact current `market_date`, unique `request_id`, and optional `search_manifest_commit`. The manifest at `config/peg_search_results.json` has `{marketDate, stocks: [{code, name, legalName, officialDomains, results: [{url, title, provider}]}]}`. An empty manifest recomputes existing evidence without source calls.

The repair retains the exact 100-stock universe, uses the shared daily publication concurrency group, validates the canonical export and fingerprint, and publishes data with the existing compare-and-swap script. Read the exact Actions run and public release after dispatch; a 204 dispatch receipt alone does not prove publication. Do not blindly repeat an ambiguous dispatch.

The original Stockscreener workflow was backed up inactive before this migration. Its original schedules and durable ledger are preserved.
