# Public OSINT Screener Answer Key

**Scope:** Public-source inventory and discovery layer for the Taiwan stock screener.

**Target worktree:** `/home/kushi/stock-web-pages-osint`

**Primary production boundary:** Official public TWSE/TPEx/TDCC/MOPS HTTP/HTML/CSV first; FinMind/yfinance only as explicitly budgeted free-quota fallbacks with provenance and cross-checks. StatementDog is the answer/reference key, never the candidate input.

**Forbidden side effects in this phase:** paid API purchase; unbudgeted FinMind/yfinance transport; blind retries after quota/ban; browser-cookie or credential extraction; cron/config mutation; git push; deployment.

**Canonical contract:** 7 groups / 33 criteria: safety 6, dividend 5, growth 5, value 6, turnaround 3, continuity 5, chip 3. Registry: `calibration/criteria_registry.json`.

**Current verdict:** `BLOCKED`

Reason: the independent public-data scorer, normalized models, runner, and offline tests now exist, but full-universe input, complete dividend/CapEx history, point-in-time publication metadata, unresolved major-holder/rank data coverage, 500-company calibration, and UI/release gates are not complete.

## Reference answer

The approved reference is the user-specified StatementDog health-check page: `https://statementdog.com/analysis/2330/stock-health-check`.[1] Existing sanitized reference evidence contains 500 distinct seven-group records; it is reference evidence only. The last recorded 2330 reference was: safety 5/6, dividend 1/5, growth 5/5, value 0/6, turnaround 1/3, continuity 3/5, chip 1/3. Do not feed these values into the candidate engine.

## Evidence gates

| QA ID | Gate | Status | Evidence / command | Observed | Negative proof | Remaining prerequisite |
|---|---|---|---|---|---|---|
| A-01 | Exact canonical registry | PASS | `python3 scripts/validate_public_contract.py` | 7 groups, 33 unique IDs, counts 6/5/5/6/3/5/3 | Registry has no duplicate IDs or missing group | None for inventory; engine still absent |
| A-02 | Public source allowlist | PASS | `python3 scripts/validate_public_contract.py` | 33 source definitions; paid API false; FinMind/yfinance conditional free fallbacks require budget | No paid endpoint, secret-bearing URL, cookie, or credential field in registry | Adapter implementation pending |
| B-01 | TWSE/TPEx live schema smoke | PASS | `python3 scripts/probe_public_sources.py --timeout 60 --out /home/kushi/.hermes/evidence/2026-09-08-public-osint-stock-screener/public-source-probe-v3.json` | 16/16 TWSE+TPEx catalog/data probes returned PASS with listed 2330 and OTC 6488 target rows | No response body stored in repository | Scale and historical adapters pending |
| B-02 | TDCC live schema/history smoke | PASS | Same v3 probe | 6/6 TDCC probes PASS: OAS, listed/OTC snapshots, free dataset metadata/CSV, weekly query POST | Synchronizer token was memory-only; report has no token/cookie | Bulk month normalization pending |
| B-03 | MOPS historical smoke | PASS | Same v3 probe | 10/10 MOPS probes PASS: 2330/6488 annual balance, income, cash-flow, monthly revenue, and insider pages returned requested-period markers | No credentials or raw MOPS response stored in repo | Bulk adapter and parser fixtures pending |
| B-04 | Two-code normalized snapshot | PASS for source collection | `python3 scripts/collect_public_snapshot.py --codes 2330,6488 --as-of 2026-09-08 --timeout 60 --out /home/kushi/.hermes/evidence/2026-09-08-public-osint-stock-screener/public-snapshot-2330-6488-v4.json` | 2330 and 6488 each produced 208 normalized fields; source failures 0; 57/55 source records; 15 explicit UNKNOWN fields per code | No raw HTML/CSV, cookie, token, or credential in output; free fallback calls 0 | Broader universe, missing-field resolution, and criterion engine pending |
| B-05 | Free-quota fallback gate | PASS for policy only | `python3 -m pytest -q tests/test_free_fallback_policy.py` | FinMind/yfinance allowed only with explicit budget; reserve/consume/overrun covered; Phase B transport 0 | No unbudgeted provider call or secret output | Separate approved provider smoke pending |
| C-02 | Ranking semantics | BLOCKED | Contract review | PE/PB/CROIC/top-50 inputs found | No invented percentile/tie/composite weights | Resolve from reference evidence or retain BLOCKED |
| C-03 | Chip scope semantics | BLOCKED | Contract review | TDCC counts and MOPS holdings available | No aggregate+individual double count | Freeze major-holder/director definitions |
| D-01 | Pure 33-criterion engine | PASS on offline fixtures | `python3 -m pytest -q screener/tests/test_public_data_models.py screener/tests/test_public_data_normalizer.py screener/tests/test_f_score.py screener/tests/test_statementdog_like_rules.py screener/tests/test_point_in_time.py screener/tests/test_unknown_semantics.py` | 35 tests pass; scorer emits all 33 IDs, pass/fail/unknown/not_applicable, formula and source hashes | No online data or gold label used in unit tests | Full-universe input and live completeness gate pending |
| E-01 | Five-code candidate/reference reconciliation | BLOCKED | No candidate rows | Reference exists | StatementDog values not used as candidate inputs | Collect public snapshots and compare |
| F-01 | 500 distinct all-seven exact calibration | BLOCKED | Not run | Existing reference has 500 rows only | Reference-only count is not candidate PASS | Need 500 eligible candidate/reference pairs |
| G-01 | UI/build/release | BLOCKED | Old UI inspected | Current UI is old four-score site | No deployment/push performed | Integrate only after F-01 |

## Public-source method contract

- Discovery uses local SearXNG only to find candidate URLs; official-host allowlist decides acceptance.
- Fetches are bounded by timeout/body cap and record only sanitized metadata.
- JSON/CSV/HTML response shape, required fields, target code, period, unit, finiteness, duplicates, and market are validated before normalization.
- MOPS historical queries use `isnew=false` plus ROC `year` and `season`; monthly revenue uses ROC `year` and `month`.[25][26][27][28]
- This model uses `FCF = CFO - positive CapEx`; `CFI` is not a silent substitute. `continuity.croic_*` IDs are compatibility aliases for the explicit FCF ROE model.
- TDCC query page is weekly; normalize to the last available weekly observation in each calendar month. A single current TDCC OpenAPI response cannot prove a three-month trend.[19][20][21][24]
- Missing, stale, malformed, wrong-period, unauthorized, or incomplete data is `UNKNOWN`/`BLOCKED`, never zero and never an inferred pass.
- FinMind/yfinance free-quota use requires an explicit request budget, preflight schema test, quota/status ledger, provider provenance, and independent official cross-check; no blind retries after HTTP 402/403/429 or equivalent quota/ban signals.
- Raw source responses stay outside the repository; snapshots keep field-level provenance, source date, fetch date, parser version, and formula version.

## Failure matrix

| Case | Expected result | Must not happen |
|---|---|---|
| Missing monitor source root | `BLOCKED` before candidate build | Empty publish artifact or fake active rows |
| Source HTTP 403/429/5xx | `BLOCKED`/`UNKNOWN` with type/status only | Blind retry storm or guessed values |
| JSON/CSV shape drift | `parse_error` and no score | Partial row promoted to valid |
| MOPS response period differs from requested period | `UNKNOWN` | Current/latest data substituted for historical period |
| Zero/invalid denominator | `UNKNOWN` | Division by zero or zero-filled score |
| Missing one year of a five-year window | `UNKNOWN` | Shortened denominator |
| TDCC only one month available | `UNKNOWN` for three-month trend | Trend inferred from one snapshot |
| Aggregate and individual ownership rows both present | Parse one canonical aggregate or `parse_error` | Double counting |
| PE/PB rank universe incomplete | `BLOCKED` | Rank computed on an unstated subset |
| Composite formula/weights unknown | `BLOCKED` | Invented weights or proxy score |
| StatementDog reference only | Reference artifact only | Reference boolean/count copied into candidate |
| Dirty checkout | Work in isolated worktree | Overwrite existing uncommitted user patch |
| Push/deploy requested before F-01 | Refuse release gate | Claiming build/calibration completion |

## Current execution record

- Plan: `.hermes/plans/2026-09-08_134619-public-osint-stock-screener.md`
- Registry: `calibration/criteria_registry.json`
- Source registry: `calibration/source_registry.json`
- Probe evidence target: `/home/kushi/.hermes/evidence/2026-09-08-public-osint-stock-screener/`
- Existing reference evidence: `/home/kushi/.hermes/evidence/2026-09-07_221223-stock-cron-operations-r10/16-statementdog-reference-7.json`

## Release rule

No production UI, commit, push, deploy, cron, or public claim of seven-score correctness until A–G applicable gates are green, especially F-01. A successful unit test, source HTTP 200, or Astro build is not calibration proof.
