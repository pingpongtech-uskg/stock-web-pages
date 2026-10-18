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

- [x] Compare exact active nodes, expressions, connections, credentials, schedule and settings against generated artifacts.
- [x] Bring already deployed recovery/date/checkpoint/publication behavior into the tracked sources, preserving credential references and graph edges.
- [x] Verify generated logic against recorded real execution fixtures before any workflow publication.
- [x] Require a fresh active-version check immediately before update and confirm draft/active parity afterward.

## Task 4: Make recovery serve website freshness

**Files:** n8n engine/outcome and new focused recovery tests, export freshness evidence if required.

- [x] Record publication date, exact public payload identity and actionable freshness gaps in durable state.
- [x] If a producer is still running, resume that exact handle; never start a second producer solely because a polling window expired.
- [x] If website publication is verified but current-session data is missing, a bounded subsequent recovery must acquire fresh data using a new explicit revision, preserving daily API budgets and the last verified website.
- [x] If website publication is current and complete, report an intentional no-op rather than implying another data refresh occurred.
- [x] Finish website readback before auxiliary archiving. Auxiliary failures must not suppress website verification or make an unverified deployment look published.
- [x] Preserve manual execution after schedule cutoffs and on non-trading days; resolve the latest completed official session and expose whether the run resumed, refreshed, or skipped.

## Acceptance scenarios

1. One stock has no latest quote: correct available stocks publish; missing quote/date remains explicit.
2. Invalid price basis, arithmetic, lineage, date or hash: reject the incorrect candidate; do not fabricate a passing number.
3. Financial provider crash/timeout: official snapshot remains usable and publishes with gaps.
4. Notion or backup outage: verified website publication remains successful with auxiliary status pending/failed.
5. Deployment delay/wrong live bytes: never report website publication verified.
6. Repeated 30-minute ticks: one active producer; later actionable gaps cause a bounded real refresh rather than archive-only replay.
7. Manual execution after cutoff/weekend: resolves the intended completed session and produces a clear result.

Final acceptance requires actual public files matching the approved immutable release, correct quote dates/bases, explicit remaining gaps, and real production recovery observations. Unit tests or n8n green status alone are insufficient.

## October 18 deployment evidence (Asia/Taipei)

- Source repair `32eedbdf99e8cb0f470d9cb2bec574b1588a9cf6`; final annotated-manifest gate `82b19796ff0013bb88e7975270158280a705fd6b`.
- n8n 317 regressions passed. SDK validation accepted all 97 nodes. Previous 41 source/live transition replays established the reconciliation baseline.
- Main active version `2cea1e66-a2eb-4b69-b7e4-05e0c2eacdb9` read back identical to draft. Exactly three intended Code nodes changed; connections, credentials, 18:00 schedule and 30-minute recovery schedule preserved. Ordinary manual defaults restored.
- Optional invalid/unavailable prior cache falls back to official acquisition only after owned CAS; checkpoint conflicts and expired leases still stop.
- Freshness recovery reads gaps across the full roster, not only selected stocks. It waits 30 minutes, uses deterministic revision IDs, caps six acquisitions per session, and preserves provider budget/cache state. Active producers are resumed.
- Advisory annotation now verifies original manifest integrity before mutation and recomputes hashes after annotation. A second mandatory snapshot check runs before export/publication. Existing tampering remains a hard failure.
- Live acceptance in progress: n8n `1837`, request `stockscreener:20261016:correct-quotes-v2`, Actions `39076738966`. Weekend manual revision passed calendar and CAS and dispatched the exact current source commit. Public byte/date/quote and archive acceptance remains pending until this run completes.

## Publication acceptance follow-up

- Manual revision `1837` / Actions `39076738966` passed numerical/manifest/cache validation, then GitHub rejected its data push because main advanced with an authorized source repair. Exact log: `HEAD -> main (fetch first)`.
- Added a data-only bounded publisher (`ace8c94`, workflow wiring `864ae4d`): rebase source-only changes, never force push, reject unrelated staged files.
- Independent review found that a clean Git merge could still combine concurrent data. Local follow-up now compares the entire `public/data` tree and tracked-symbol config blob against the validated candidate after every rebase, before every push. Added real local-remote regressions for disjoint data/config additions, changes/deletions, retry races, ambiguity and retry bounds.
- Manual revision `1841` / Actions `39081186161` failed the Python gate. Local reproduction showed two structural tests still searching the previous inline `git add` command. Updated their publication-step locator to the new publisher invocation; all numerical, fingerprint and ordering assertions retained. Focused publication/snapshot/fingerprint suite: 55 passed.
- Final publisher/test follow-ups are LOCAL ONLY, not pushed. No successful live acceptance of this revision has been claimed. Full Python suite: 1,163 passed, one skipped. Focused safety tests include protected config add/change/delete, disjoint data add/delete, source/data push races, ambiguous accepted push and exactly three attempts on persistent rejection.
- External GitHub query was rejected by automatic approval review because the workspace owner spend cap prevented the approval review from completing. This is an approval service failure, not a security determination. User guidance requested; do not bypass the approval check.
- Temporary Personal/root manual repair publisher workflow `Vd5adk3wbzH68VVs` was archived after use. Main Stockscreener remains active, ordinary manual defaults restored, active version `a3cec831-af7a-44b0-8a21-17310ed9934f`.

Local checks: shell syntax and `git diff --check` passed. Offline npm audit reported zero cached advisories (not a fresh registry audit). pip-audit could not evaluate range-based requirements with `--no-deps`; dependencies were unchanged. Final independent reviewer could not complete its post-fix turn because the workspace spend cap was reached; parent reviewed the protected-object comparison and all added integration regressions passed.
