# Stockscreener workflow

The existing workflow is `huDBNJDss4KuPmn4`, titled **Stockscreener**. The backend has been promoted to main commit `2451036717641cd4827dbdc3856f8af8ac462fc6` and its deployed UI/archive were verified. This workflow remains inactive while explicit human approval for the controlled production run, imports, retry proof, and activation is pending. The generated SDK and JSON live in `scripts/n8n/`; edit `engine.cjs`, `runtime.cjs`, or `build-workflow.cjs`, then run the generator. The JSON contains credential identifiers, never credential secrets.

## Schedule and ownership

The main schedule is `0 18 * * 1-5` in `Asia/Taipei`. A second schedule reconciles every ten minutes from 18:00 through 20:50 on weekdays. It uses the same stable date/request key and skips an already verified operation. The installed Schedule Trigger v1.4 accepts durable `misfirePolicy: coalesce`; bounded evening reconciliation also covers an omitted same-day dispatch.

The expected market date comes from the local Taipei date, checked against the independently fetched TWSE holiday calendar. ROC dates are converted to ISO dates, calendar year must match, and explicit opening events are distinguished from closures. Invalid, empty, unavailable, or mismatched-year calendars fail closed. Closed days produce a skip ledger and no Actions dispatch or Notion stock database. Historical recovery requires an explicit operator date and exact Actions request/run; the workflow never fabricates a market date from stale quote data.

Each writer claims `operations/days/YYYY-MM-DD.json` on the separate GitHub branch `n8n-state`. A new file is created without a SHA; an existing file is updated with its observed blob SHA. Conflicts abort the follower. Every checkpoint commit starts with `[CF-Pages-Skip]` so state writes do not trigger Cloudflare preview builds. Data Tables are an audit ledger, not a uniqueness or lock authority.

The instance enforces a 3600-second execution maximum. Each execution has a 59-minute writer deadline. A successor may take ownership only after that deadline plus 60 seconds, exceeding the maximum 20-second HTTP request duration. A gate after every Wait node prevents the old owner from starting another operation after its deadline. Scheduled recovery keeps the original absolute 19:30 Taipei operation cutoff; it does not start another 90-minute daily window. The target remains 18:45. A 65-minute Actions job can therefore be resumed by the 19:10 checkpoint using the persisted exact run ID, without dispatching again. Explicit manual resume is allowed after the scheduled cutoff with a fresh 90-minute operation window; its original scheduled cutoff and manual override timestamp remain in the audit state. It still cannot take a live lease.

## Manual operation

Use the **Manual operator test or recovery** trigger and edit the **Operator inputs** fields before running:

- `mode=diagnose`: default; reads the live calendar and existing Notion database/data source, then records diagnostic status.
- `mode=screen`: dispatch the requested date only if its exact stable request has no recorded dispatch or matching Actions run.
- `mode=resume`: find the same exact request/run and resume artifact retrieval, Notion archive, or deployment verification. It never dispatches a missing run.
- `mode=legacy_archive`: authenticated immutable backfill for the six retained dates: 2026-09-08, 09-11, 09-18, 09-23, 09-24, and 10-01. It pins a verified main commit, reads index/month/revision evidence, verifies raw SHA-256 and date/run/revision, and archives the actual strategy union without screening. Original Actions/source lineage remains unknown; ingestion commit, legacy quality, original strategy rows, absent metric nulls, and revision hash remain explicit. Deployment checks the historical revision path.
- `mode=revision`: a correction with a new `request_id`. Existing stock revisions remain in the same child database; `Active Revision` moves only after the new selected union is verified.
- `market_date`: `YYYY-MM-DD`; blank uses the current Taipei date.
- `request_id`: the exact dispatch correlation ID; blank uses `stockscreener:YYYYMMDD:v1`.
- `actions_run_id`: optional exact known run; the run title and source commit still must match.
- `run_kind=manual`: retain for manual recovery. Scheduled inputs use `scheduled` and enforce the original 19:30 cutoff.

Restore `mode=diagnose` and blank operator date/request/run after a test or recovery. Changing manual inputs does not change scheduled input values.

## Artifact and archive integrity

The GitHub run title must equal `Daily screening | REQUEST_ID | MARKET_DATE`; ambiguous matches fail closed. The artifact must be the single non-expired `screening-export` artifact from that exact run. Authenticated artifact lookup is followed by a signed download without forwarding GitHub credentials. The native Compression node extracts `screening-export.json` and `publication.json`.

The workflow hashes the exact UTF-8 preimage from the export's final `payloadHash` suffix, avoiding JavaScript/Python float reserialization differences. It verifies schema, date, request ID, Actions run ID, source commit, publication lineage, unique strategy ranks/codes, and the deduplicated selected-stock union. It rejects stale-universe exports. A valid empty union creates a complete empty child database; failed screening creates daily failure metadata and no child database or fabricated zero result.

The root Notion database is `3ed6fb57-ff38-8032-97cc-f017b6104300`; its data source is `3ed6fb57-ff38-803d-815a-000b148c6b6e`, and its title property is `名稱`. Each root record is titled `YYYYMMDD` and contains an inline child database titled `YYYYMMDD`. Database IDs and data-source IDs are stored separately. The HTTP nodes pin `Notion-Version: 2025-09-03` and disable header lowercasing: otherwise the existing credential's legacy-version fallback overrides the intended API version.

Stock codes use rich text and retain leading zeroes. Each stock row stores strategy tags, strategy ranks, numeric metrics, the complete metric JSON, provenance, formula/financial evidence, revision, payload hash, and the stable `Row Key=PAYLOAD_HASH:CODE`. Same-payload retries query existing keys before creating. Ambiguous create responses return to a read operation. Proven identical duplicate stock rows can be archived deterministically while preserving the oldest row; unrelated records and prior revisions are preserved. Parent block lists and stock queries are paginated.

All Notion requests are spaced at least 500 ms apart. HTTP 429 responses respect `Retry-After`, with a bounded retry count. Write nodes do not use blanket native retry settings. CAS checkpoints persist exact Actions/artifact/run IDs and discovered Notion IDs. Immutable artifact bytes are retrieved again during recovery rather than copied into the state ledger. Signed download URLs remain transient: success/error execution payload saving, manual execution saving, and execution-progress saving are disabled. The durable state and ledger exclude operation URLs and stock payloads. The live site host is pinned to `stockscreener.andyshih.uk`; operator Actions IDs must contain decimal digits only.

## Independent statuses and failures

Screening, Notion archive, and Cloudflare deployment statuses are separate. Deployment verifies `https://stockscreener.andyshih.uk/data/screening-export.json` against the exact run/date/request/hash. A first probe occurs before Notion writes; a second bounded poll runs after archive verification, up to five minutes. Deployment failure does not discard a valid Notion archive. A subsequent same-request recovery checks deployment again without rescreening.

Durable CAS state is the recovery authority. Append-only n8n Data Table `JWOzPb7PlUVqGC1g` stores operation outcomes, independently queryable by date/request/run/hash. Every failure has a category and short explanation. Ambiguous checkpoint writes abort; recovery first re-reads the server's state. A dispatch whose response was ambiguous is searched by the exact request title and is never blindly sent again.

## Verification

Run `node --test --experimental-test-coverage scripts/n8n/test-*.cjs` and `node scripts/n8n/build-workflow.cjs`. Validate every node config and the SDK through the installed n8n tooling before updating the remote draft.

`runtime-evidence.json` separates actual server executions from local unit fixtures. Execution 707 verified the real calendar and modern Notion metadata. Execution 708 verified real GitHub create/competing-create/exact-SHA/stale-SHA responses and removed its owned temporary diagnostic file; its temporary workflow was archived. Automatic approval review rejected the October 2 live execution before an execution ID or Actions dispatch existed. Its stated reason was that exact screening, Notion writes, and main-to-Cloudflare production publication lacked explicit user authorization. Diagnostic defaults have been restored. Real Actions-artifact-to-Notion-to-live-deployment acceptance remains pending human approval; no workaround execution was attempted. Local tests never create fake production dates or stock records.

Primary API references: [GitHub Contents compare-and-swap](https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28), [Notion database creation](https://developers.notion.com/reference/create-a-database), and [n8n concurrency behavior](https://docs.n8n.io/hosting/scaling/concurrency-control/).

A temporary read-only seven-date audit helper (`TIgXL66Fg0bw5NqQ`) independently queries each active payload child source, paginates stock rows, and records actual count, unique Row Keys, codes, revision/hash and root Expected/Archived Count in the durable ledger. Its generated source is `archive-audit.workflow.sdk.ts`; it stays inactive and will be archived after acceptance proof.
