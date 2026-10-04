# Official chip supplementation: accepted execution plan

Date: 2026-10-04. Discovery baseline: `353519c`; collaborators may change line numbers during implementation. This document records the approved scope and verification gates, not a claim that collection or deployment has completed.

## Accepted scope and formulas

- Use free official TDCC, MOPS and exchange open data. No paid FinMind chip endpoint, inferred ownership, login or challenge bypass.
- Probe `2547,3005,2404,2376,3293`, then the twelve selected stocks from the frozen October 2 screening export, then all 100 configured A-universe stocks. Obtain the twelve from the actual export, deduplicate their union, and retain an evidence file with the exact roster; do not guess remaining codes.
- For an October 2 release, trend months are **July, August, September 2026**, the last three completed calendar months. Choose the last available official TDCC weekly observation within each month. October/current-week data may be displayed separately and must not replace September in the three-point comparison.
- TDCC class 15 supplies `占集保庫存數比例%`; class 17 supplies official total `人數`; class 16 is a difference adjustment and is excluded. HTML total labels can appear at sequence 16: map the semantic total to CSV class 17, not table row position.
- Increasing means `July < August < September`; shareholder decline means `July > August > September`. These are three monthly points and **two strict changes**. Label this accurately, e.g. `最近三個完整月份：兩次變化均上升／下降`; do not promise three changes.
- Director/supervisor rule is current valid monthly percentage **greater than or equal to** the exact same month twelve months earlier. Keep the approved role scope (`董事長本人`, `副董事長本人`, `董事本人`, `獨立董事本人`, `監察人本人`), exclude representatives/managers/relations, and deduplicate the same owner across overlapping roles using official identity evidence. Identical holding amounts alone do not establish the same owner.
- Each director percentage requires its own same-period official issued common-share denominator, with provenance and period. Current company-basic shares cannot silently become a historical denominator. The MOPS `allDirectorSupervisor` total is holdings, not issued shares. Missing denominators, identity ambiguity, non-comparable scope/corporate actions, unavailable history, or conflicting observations yield `unknown` with a reason. Preserve the existing conservative denominator-change comparability gate until a documented policy proves a comparison valid.
- Chip remains display-only. Every strategy roster, order, count, funnel, score and existing qualification rule remains identical. All three strategy tabs show the same chip semantics.

## Repository evidence and integration points

The following are observed APIs, not newly verified historical-source capabilities:

| Location at discovery | Existing behavior | Required boundary |
|---|---|---|
| `scripts/fetch_ownership.py:31–36` | TDCC latest CSV `getOD.ashx?id=1-5`, official session page `qryStock`, MOPS `/mops/api/stapap1`, TWSE `t187ap11_L/P`, `t187ap03_L/P` | Retain known endpoints; prove historical response fields before enabling adapters |
| `scripts/fetch_ownership.py:176` `fetch_tdcc_historical` | Fresh synchronizer token/cookie GET plus POST for each probed date; scans backward at most eight days | Both GET and POST count as actual requests; durable next date/cursor prevents repeatedly starting month scans |
| `scripts/fetch_ownership.py:229` `parse_mops_payload` | Director numerator parsed; denominator deliberately absent | Attach denominator only with same-period official evidence; never manufacture percentage |
| `scripts/fetch_ownership.py:272` `parse_twse_director_rows` | Attaches current company-basic shares to any director month | Fix same-period proof; same retrieval time is insufficient |
| `scripts/fetch_ownership.py:348` `fetch_mops` | Historical request function exists | Active `fetch_ownership_rows` currently never calls it; existence is not history coverage |
| `scripts/fetch_ownership.py:361`, `421` | Targets offsets `(-2,-1,0)` from as-of month; iterates requested codes in order | Completed-month target offsets `(-3,-2,-1)` and persistent fair queue |
| `pipeline/ownership_inputs.py:59`, `106`, `138` | Hardcoded `TWSE`; role aggregation lacks identity dedup; merge keys code/month | Correct market for TPEx e.g.3293; preserve source/identity/denominator provenance and conflict detection |
| `pipeline/ownership_checks.py:55` `_trend` | Chooses newest three periods from mixed normalized rows | Explicit requested completed-month window; director-only months/current week cannot displace TDCC months |
| `scripts/refresh_snapshot.py:230`, `1346` | Loads ownership separately; missing path overwrites references with unavailable | Pass verified cache to first refresh **and** recompute-existing; verify both paths |
| `.github/workflows/daily.yml`, ownership steps | Synchronous fetch before daily refresh, mutable Actions cache checkpoint | Replace network producer in the 18:00 path with bounded verified-cache read |
| `.github/workflows/daily.yml`, `Recompute from existing enriched inputs without network` | Omits `--ownership-snapshot` | Ensure later recompute retains the same pinned verified chip generation |
| `scripts/build_market_cache_index.py:230`, `260` | `published_stock_inputs` contains whole stock detail, plus institutional/calendar/volume groups | Notion full cache includes chip display summaries inside detail evidence; it does **not** include a standalone ownership producer snapshot/queue |
| `pipeline/market_cache_restore.py:243` `_plan` | Restores receipts and whole stock evidence files | Restoring chip display evidence is not restoring the producer's raw monthly history/queue |
| `scripts/n8n/cache-restore-operation.cjs:1`, `21`, `68` | Credentialed Git state custody, immutable data-only restore commit | Reuse tested custody principles; do not execute files from data branches or replace existing Notion flow |
| `scripts/n8n/source-operation.cjs:68` and tests | Non-forced Git ref updates and readback | Match no-force atomic publication and exact readback for chip state |
| `src/components/StrategyCard.tsx:141–143` | Existing `連續三月` status copy | Copy correction must state three completed months/two changes |

Historical endpoint names and parameters in this table come from repository code. Live probes remain required; this plan does not declare that any missing director denominator API exists.

## Persistent shared cache and concurrency design

Use a **dedicated data-only Git branch** (proposed `chip-state`, distinct from `main` and `n8n-state`) as the durable authority. Reuse the repository's existing Git custody approach rather than using evictable Actions cache as authority. Actions artifacts mirror each run for audit/recovery. Preserve existing Notion cache roles by adding an optional explicitly validated `ownershipBundle` beside `rows` in `published_stock_inputs.body`. This backs up the pinned manifest, normalized monthly history, durable queue and sanitized raw receipt bytes with hashes. Python producer/restore and n8n semantic validators verify the bundle; restore materializes standalone ownership producer state. Legacy absence remains valid but cannot claim ownership backup complete. Adding a new group requires changing exact role validators and is unnecessary for this minimal path.

One serialized Actions chip workflow owns branch writes. Its concurrency group is constant across all chip dispatches and `cancel-in-progress: false`. n8n dispatches weekday `17:00`, `17:15`, `17:30` Asia/Taipei with unique request IDs. Overlap cannot authorize two writers; dispatch order is not a fairness guarantee. Root owns live activation and may retain the 97-node no-AI daily main graph intact by deploying an independent chip scheduler.

Every invocation has at most **20 actual official-source HTTP requests** and **180 seconds of acquisition time**. Requests include failed attempts, redirects if permitted, token GETs, query POSTs, bulk requests and retries. Centralize the shared counter/deadline across TDCC, MOPS and exchange adapters; subtract time already elapsed before blocking reads/backoff. No alternate fetcher bypasses this budget. Persistence/setup have their own explicit bounded workflow timeout and do not expand acquisition limits.

Publish a generation containing normalized ownership, validated receipt references, pending queue and a manifest in **one Git commit**. Manifest binds schema/formula version, release as-of, requested universe hash, target months, source code commit, Actions run/attempt, request ID, previous generation SHA, all file hashes and real coverage. Immutable raw objects are addressed by hash; reject symlinks, path traversal, oversize bodies, future period/publication and unsafe source origins. Tokens/cookies are transient and never persisted. Branch contains data only; trusted main supplies verifier code.

Read initial state at a pinned commit, verify bytes and manifest, mutate only local copies, publish a descendant commit with a non-forced update, and read back exact commit/hash. On conflict, never force or overwrite another writer: bounded reload/merge using verified observation identity, or preserve the run artifact and leave the queue pending. Corrupt generation is not promoted. Atomic local replacement is still needed; a mutable `ownership_snapshot.json` uploaded by unrelated runs is not sufficient.

At 18:00 daily workflow resolves and pins one existing generation, verifies it with trusted code, and materializes `.cache/ownership_snapshot.json`. It never waits for chip jobs, loops for a future generation, or starts official chip acquisition. Missing/corrupt/unusable cache gives truthful stale/unavailable references while existing price/strategy publication continues. Both refresh invocations receive the pinned cache. Cache generation, actual source periods and missing reasons remain visible in release evidence. A chip producer finishing later becomes available to a later daily/correction release; it cannot change a running release's cache bytes.

## Durable queue and honest coverage

Queue key is source + stock + target period + task kind. TDCC work may additionally retain candidate date/session step. Director holdings and issued-share evidence are separate dependencies. Rows are completed only after semantic validation; HTTP200, empty table, challenge page and token success are not completed tasks.

Persist attempts, last attempt/error, next eligible time, cursor, completed receipt and terminal/block reason. Rotate across stocks and missing months, with dependency-aware scheduling and bounded retries/backoff. A failed first code must not consume each subsequent invocation forever. A token+POST pair requires enough remaining budget/time; never restart all completed months on every run. Prior completed tasks are skipped by validated period/source identity. Refresh current bulk TDCC at most as the budget allows, but reserve historical progress instead of spending all requests re-fetching already-complete latest data.

Stages prioritize the five-stock probe, then twelve selected, then all 100; existing completed work survives stage promotion. Universe coverage is best effort over repeated bounded jobs. Report separate TDCC `0..100` complete three-month counts, director exact12m coverage, pending/retry/blocked counts, and actual attempts. Never label the full universe complete because every stock has one current CSV row or because a job exited successfully. No fixed date promise for 100-stock completion follows from 60 requests/day.

## Implementation responsibility boundaries

| Owner | Exclusive edits/responsibility |
|---|---|
| Architecture/document worker | This plan only; read-only integration discovery |
| Backend worker `/root/chip_backend` | `scripts/fetch_ownership.py`, new `scripts/update_ownership_checkpoint.py`, pending queue/raw receipt contract and backend tests; source acquisition, request accounting, persistent progress. Own `pipeline/ownership_inputs.py` normalization and its tests; coordinate schema with rules owner |
| Rules/UI worker `/root/chip_rules_ui` | `pipeline/ownership_checks.py`, frontend types/API/copy and tests; completed-month evaluation (`evaluation_date=as_of`), identity/provenance, truthful labels |
| Workflow/cache worker | Dedicated `.github/workflows/ownership.yml`, `.github/workflows/daily.yml`, new chip state manifest/verification/restore helpers, protected optional Notion ownership bundle and their tests; scheduler generator files agreed with root; serialize/pin/persist/no-network daily integration |
| Root/integration | Shared `scripts/refresh_snapshot.py`, release/archive correction, docs other than this plan, live n8n/GitHub/Notion operations and deployment/readback |

Proposed filenames are not claims that APIs already exist. Producer CLI proposal: `scripts/update_ownership_checkpoint.py --verified-market-date YYYY-MM-DD --state-dir PATH --snapshot-output PATH --roster-publication PATH [--priority-codes csv] [--max-requests 20 --max-runtime-seconds 180]`. Validate canonical export with `pipeline.screening_export.validate_export`; priorities from `selectedStocks[].code`, universe from configuration.

Freeze the backend snapshot/queue and manifest schema before workflow implementation; pass explicit parameters rather than adapters importing workflow state. If owners need a shared file, coordinate first. Do not revert peers' edits.

## Verification phases

1. **Baseline and failing tests.** Freeze October2 code/roster/strategy projections and cache manifest. Add meaningful tests for July–September versus October contamination, mixed director months, equality in12m comparison, source role dedup ambiguity, same-period denominator proof, TPEx market, request20/time180 boundaries and every source failure. Record red then green. Target at least80% coverage for changed backend modules, plus integration and critical UI end-to-end checks under repository policy.
2. **Five-stock official probe.** Root captures HTTP status/content type, body hash, retrieval time, official reported date/month, parsed class15/class17 rows, director identity/scope and denominator evidence. Preserve sanitized fixtures. Check source-reported dates; do not assign a requested date to an undated response and call it verified. If a historical denominator/identity is unavailable, record the exact `unknown` reason and continue other tasks.
3. **Twelve selected.** Root confirms exact roster from frozen export. Complete whatever official sources permit, render current week separately, and prove release chip fields match verified cache bytes. Exercise interrupted acquisition/restart with queue progress preserved and two overlapping dispatches with one writer.
4. **All100 durable rollout.** Seed remaining tasks without resetting existing completion. Prove fairness with a persistently failing first stock, cooldown, budget exhaustion mid-token/query, month rollover and a changed tracked universe. Artifact recovery and invalid state tests must avoid promoting incomplete/corrupt generations.
5. **Daily integration.** With source calls disabled, run cache restore + initial refresh + financial enrichment + recompute. Assert no chip network calls and identical selected stock codes, ranks, counts, funnels, scores and raw strategy metrics. Verify existing complete Notion market-cache export/restore roundtrip remains valid and carries corrected display evidence. Prove ownership bundle raw receipt/normalized/queue bytes roundtrip into verified standalone producer state; corruption fails closed, legacy absence is honest.
6. **October2 chip-only correction.** Minimal integration is a distinct `source_mode: ownership_recompute` job in `daily.yml`, sharing established request/run/artifact identity. It consumes a pinned generation, performs no chip/FinMind/price acquisition, and runs chip-only correction plus normal fingerprint/export/market-cache/history/build gates. Validate source-mode inputs on existing jobs; test Notion consumer compatibility.  Build an immutable corrected archive revision from frozen October2 inputs; change only chip fields and necessary revision/hash/lineage metadata. Do not refresh market data or recalculate a different roster. Keep old revision accessible, validate canonical screening export/history/fingerprint, and compare strategy projection to baseline before root publication. Treat source data known only after October2 honestly: preserve retrieval/publication proof and do not invent point-in-time availability.
7. **Remote readback.** Root checks active chip schedule timezone/three times, main18:00 no-block behavior, generated SDK/runtime graph parity, Actions logs/artifact hashes, published chip fields and Notion cache verified state. Remote activation/publication status and actual collection coverage are separate outcomes.

## Required evidence and remaining risks

- Official response evidence is required for each parser field and historical denominator, not just a document link or endpoint returning200. Existing September21 source evidence proves latest official datasets were reachable then; it does not prove October historical completeness.
- TDCC date probes can use two requests per candidate and may exhaust20 before five stocks finish; durable date cursors and fair retries make this recoverable, not a reason to increase approved budget.
- Free MOPS historical responses may lack issued shares/unique identities. Keep director comparison unknown; do not silently use current denominators or unrelated totals to improve coverage.
- Existing normalization collapses code/month source provenance. Preserve independently verified metrics without laundering one source's dates into another's freshness; stale status should be granular enough to explain incomplete fields.
- Existing recompute path can erase a valid chip reference if its cache argument is missing. This is a release integration gate, even when all producer tests pass.
- Git state write authorization, branch protection, artifact retention and source challenge behavior must be proven in the actual environment. Data branch is the durable authority; Actions artifacts/cache and Notion display copies are not substitutes for verified producer state.
- No declaration of full100 completion, director12m coverage, active schedule or public correction until exact readback evidence exists. Pending/blocked official-source tasks are an acceptable truthful best-effort outcome.

## Implementation evidence notes

Root reports the five-stock official probe verified with 55 actual HTTP requests across bounded runs. This is source-probe evidence, not full100 coverage or a promise of director12m denominator completeness. Source role discovery confirms `副董事長本人` belongs in the approved self-role scope. Cache-only refresh integration now has a dedicated `--ownership-recompute` CLI, explicit release evaluation date, a non-chip invariant guard, canonical manifest hashing and stale display preservation on missing cache. Remote correction/backup/schedules still require readback gates above.
