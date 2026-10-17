# Reliable Website Publication Implementation Plan

> **For agentic workers:** Use the existing subagent review and execution workflow. Preserve production fixes and verify current external state before deployment.

**Goal:** Publish correct available data for every completed trading session, disclose missing or older observations, and make recovery acquire missing data instead of merely replaying a successful archive.

**Architecture:** The required path is official session resolution, acquisition, numerical validation, immutable publication, deployment, and public readback. Financial supplementation, Notion archiving, and backup transport are auxiliary and must not prevent an otherwise valid website release. Hashes establish byte identity; numerical and date validation establish whether those bytes represent the intended data.

**Tech Stack:** n8n credential nodes, GitHub Actions, Python publisher, static React site, Notion auxiliary archive.

## Evidence and existing fixes

- Active n8n version `8ef49b24-bcbc-4d0e-8aec-3b0f9e0589a5` has 97 nodes and 30-minute recovery checkpoints. Do not restore the older generator's five-minute schedule or 19:30 hard cutoff.
- October 16 failure `1779`/Actions `38884306409` was a growth valuation contract mismatch. Commit `681deae` fixed it with regression tests; do not redo or weaken that gate.
- Recovery `1783` published October 16 and verified 13 Notion rows. Public snapshot bytes matched immutable publication commit `cef406b53a835cdb023048fce25d93a9a15f889e` and the publication SHA-256.
- `6173` remained dated October 15, explicitly warned. Optional cache QA failed `cache_detail_date`; publication continued. That existing advisory behavior must remain.
- Checkpoint `1799` still used the same Actions run, run ID, revision and payload hash as `1783`. Green recovery executions did not fetch the missing quote again.
- Exact producer replay proved that an October 15 raw close of 100 plus an October 16 adjusted-only observation of 95 can become an October 16 raw price of 100 with an adjusted return. Correcting this is required before claiming numerical correctness.
- The tracked n8n generator differs from active behavior. A wholesale rebuild would regress existing fixes; reconcile against the live graph before deploying source changes.

## Task 1: Keep quote value, basis and date together

**Files:** `scripts/refresh_snapshot.py`, `pipeline/test_raw_quote_contract.py`, relevant existing refresh tests.

- [x] Reproduce mixed-date raw/adjusted rows, adjusted-only rows, and offline baselines with the actual producer.
- [x] Select a finite positive raw quote and its date from the same row; never substitute adjusted close into the raw quote column.
- [x] Compute raw return only from corresponding raw observations. Keep adjusted research values separate.
- [x] Preserve missing quotes as null/unknown and retain their actual date, independently of regression history end.
- [x] Use the independently requested trading date as release identity; retain per-stock source dates even when older or absent.
- [x] Run the dedicated raw-quote regressions plus refresh, valuation and freshness tests; review downstream valuations for mismatched PE dates.

Acceptance example: raw October 15=100/adjusted=90, October 16 raw missing/adjusted=95 must not produce a current raw quote of 100 or raw return of 5.56%. Adjusted-only data must not produce a raw quote at all.

## Task 2: Isolate optional enrichment and backup transport

**Files:** `.github/workflows/daily.yml`, `scripts/run_optional_supplement.py`, wrapper regression tests.

- [x] Run optional supplementation against a staged copy of the already acquired official snapshot; keep FinMind budget and receipts outside that transaction.
- [x] On subprocess failure or bounded timeout, stop the child, discard staged data, and continue with the intact official snapshot.
- [x] On completed supplementation, promote staged data with rollback for filesystem failures. Subsequent recompute and mandatory correctness gates still apply.
- [x] Make optional market-cache artifact upload advisory as well as cache construction; report its failure explicitly.
- [x] Prove with real temporary directories that partial failed writes cannot alter official bytes, success promotes, timeout waits for child termination, and failed promotion restores the baseline.

Verification: 1,144 Python tests passed, one skipped; independent correctness review found no blocking defects. Production rollout and public readback remain required.

## Task 3: Reconcile deployment sources with the active workflow

**Files:** `scripts/n8n/engine.cjs`, `outcome.cjs`, `build-workflow.cjs`, cache operation modules, generated workflow JSON/SDK and their tests.

- [ ] Compare exact active nodes, expressions, connections, credentials, schedule and settings against generated artifacts.
- [ ] Bring already deployed recovery/date/checkpoint/publication behavior into the tracked sources, preserving credential references and graph edges.
- [ ] Verify generated logic against recorded real execution fixtures before any workflow publication.
- [ ] Require a fresh active-version check immediately before update and confirm draft/active parity afterward.

## Task 4: Make recovery serve website freshness

**Files:** n8n engine/outcome and new focused recovery tests, export freshness evidence if required.

- [ ] Record publication date, exact public payload identity and actionable freshness gaps in durable state.
- [ ] If a producer is still running, resume that exact handle; never start a second producer solely because a polling window expired.
- [ ] If website publication is verified but current-session data is missing, a bounded subsequent recovery must acquire fresh data using a new explicit revision, preserving daily API budgets and the last verified website.
- [ ] If website publication is current and complete, report an intentional no-op rather than implying another data refresh occurred.
- [ ] Finish website readback before auxiliary archiving. Auxiliary failures must not suppress website verification or make an unverified deployment look published.
- [ ] Preserve manual execution after schedule cutoffs and on non-trading days; resolve the latest completed official session and expose whether the run resumed, refreshed, or skipped.

## Acceptance scenarios

1. One stock has no latest quote: correct available stocks publish; missing quote/date remains explicit.
2. Invalid price basis, arithmetic, lineage, date or hash: reject the incorrect candidate; do not fabricate a passing number.
3. Financial provider crash/timeout: official snapshot remains usable and publishes with gaps.
4. Notion or backup outage: verified website publication remains successful with auxiliary status pending/failed.
5. Deployment delay/wrong live bytes: never report website publication verified.
6. Repeated 30-minute ticks: one active producer; later actionable gaps cause a bounded real refresh rather than archive-only replay.
7. Manual execution after cutoff/weekend: resolves the intended completed session and produces a clear result.

Final acceptance requires actual public files matching the approved immutable release, correct quote dates/bases, explicit remaining gaps, and real production recovery observations. Unit tests or n8n green status alone are insufficient.
