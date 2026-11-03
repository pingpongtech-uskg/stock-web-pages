'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { validDate, requestIdFor, plan, claim, finish, recordDispatchIntent } = require('./peg-publication-state.cjs');

const day = '2026-11-04';
const requestId = 'peg-2026-11-04-ttm-v1';
const sha = 'a'.repeat(40);
const commit = 'b'.repeat(40);
const latest = { marketDate: day, runId: 'enriched-latest' };
const manifest = { marketDate: day, generatedAt: '2026-11-04T12:00:00Z', stocks: [{ code: '2330', results: [] }] };
const missingFile = { statusCode:  404, body: { message: 'Not Found' } };
const existingFile = { statusCode: 200, body: { sha, content: 'ignored-by-pure-planner' } };
const putSuccess = { statusCode: 201, body: { commit: { sha: commit } } };
const successRun = { id: 77, status: 'completed', conclusion: 'success', display_title: `PEG repair | ${requestId} | ${day}` };

test('date validation creates stable daily request ID independent of release run ID', () => {
  assert.equal(validDate(day), true);
  assert.equal(validDate('2026-02-29'), false);
  assert.equal(validDate('2024-02-29'), true);
  assert.equal(requestIdFor(day), requestId);
  assert.equal(requestIdFor(day), requestIdFor(day));
  assert.throws(() => requestIdFor('2026-13-01'), /peg_market_date/);
});

test('stale latest, date mismatch, invalid manifest, and fatal provider search cannot plan a publication', () => {
  assert.equal(plan({ marketDate: day, latest: { marketDate: '2026-11-03' }, manifest }).status, 'stale_public');
  assert.equal(plan({ marketDate: day, latest, manifest: { ...manifest, marketDate: '2026-11-03' } }).status, 'manifest_date_mismatch');
  assert.equal(plan({ marketDate: day, latest, manifest: { ...manifest, stocks: {} } }).status, 'manifest_invalid');
  assert.equal(plan({ marketDate: day, latest, manifest: { ...manifest, outcome: 'configuration_required' } }).status, 'source_search_fatal');
  assert.equal(plan({ marketDate: day, latest, manifest: { ...manifest, providerSearchFatal: true } }).status, 'source_search_fatal');
  assert.equal(plan({ marketDate: '2026-02-30', latest, manifest }).reason, 'invalid_market_date');
});

test('manifest PUT plan handles absent file as create and canonicalizes deterministic daily request ID', () => {
  const source = { stocks: [{ results: [], code: '2330' }], generatedAt: manifest.generatedAt, marketDate: day };
  const first = plan({ marketDate: day, latest, manifest: source, contentsResponse: missingFile });
  const second = plan({ marketDate: day, latest, manifest: { marketDate: day, generatedAt: manifest.generatedAt, stocks: source.stocks }, contentsResponse: missingFile });
  assert.equal(first.status, 'manifest_publish_ready');
  assert.equal(first.path, 'config/peg_search_results.json');
  assert.equal(first.expectedSha, null);
  assert.equal(first.requestId, requestId);
  assert.equal(first.content, second.content);
  assert.match(first.content, /"requestId":"peg-2026-11-04-ttm-v1"/);
  assert.equal(first.content.endsWith('\n'), true);
  assert.equal(first.content.includes('base64'), false);
});

test('existing Contents SHA is included for compare-and-swap update', () => {
  const result = plan({ marketDate: day, latest, manifest, contentsResponse: existingFile });
  assert.equal(result.status, 'manifest_publish_ready');
  assert.equal(result.expectedSha, sha);
  assert.equal(result.path, 'config/peg_search_results.json');
  assert.equal(plan({ marketDate: day, latest, manifest, contentsResponse: { statusCode: 500, body: {} } }).status, 'manifest_contents_unavailable');
});

test('dispatch is blocked until a successful Contents PUT returns a valid commit SHA', () => {
  const noPut = plan({ marketDate: day, latest, manifest, contentsResponse: missingFile, manifestPutResponse: { statusCode: 201, body: { commit: {} } } });
  const badPut = plan({ marketDate: day, latest, manifest, contentsResponse: missingFile, manifestPutResponse: { statusCode: 422, body: { commit: { sha: commit } } } });
  assert.equal(noPut.status, 'manifest_publish_failed');
  assert.equal(badPut.status, 'manifest_publish_failed');
  const ready = plan({ marketDate: day, latest, manifest, manifestPutResponse: putSuccess });
  assert.equal(ready.status, 'dispatch_ready');
  assert.equal(ready.manifestCommitSha, commit);
  assert.deepEqual(ready.action, {
    method: 'POST',
    path: '/repos/pingpongtech-uskg/stock-web-pages/actions/workflows/peg.yml/dispatches',
    body: { ref: 'main', inputs: { market_date: day, request_id: requestId, search_manifest_commit: commit } },
  });
});

test('any matching pending or failed Actions run suppresses blind redispatch', () => {
  const pending = { id: 71, status: 'in_progress', display_title: `PEG repair | ${requestId} | ${day}` };
  const failed = { id: 72, status: 'completed', conclusion: 'failure', display_title: `PEG repair | ${requestId} | ${day}` };
  const pendingResult = plan({ marketDate: day, latest, manifest, contentsResponse: missingFile, workflowRuns: { workflow_runs: [pending] } });
  const failedResult = plan({ marketDate: day, latest, manifest, contentsResponse: missingFile, workflowRuns: [failed] });
  assert.equal(pendingResult.status, 'existing_run_pending');
  assert.equal(pendingResult.run.id, '71');
  assert.equal(failedResult.status, 'existing_run_failed');
  assert.equal(failedResult.run.conclusion, 'failure');
});

test('completed success counts as published only when review and latest lineage all match', () => {
  const review = { marketDate: day, requestId, runId: 'enriched-77' };
  const current = { marketDate: day, runId: 'enriched-77' };
  const done = plan({ marketDate: day, latest: current, manifest, workflowRuns: [successRun], review });
  assert.equal(done.status, 'publication_complete');
  assert.equal(done.runId, 'enriched-77');
  assert.equal(plan({ marketDate: day, latest: current, manifest, workflowRuns: [successRun], review: { ...review, requestId: 'other' } }).status, 'existing_run_success_publication_pending');
  assert.equal(plan({ marketDate: day, latest: { ...current, runId: 'different' }, manifest, workflowRuns: [successRun], review }).status, 'existing_run_success_publication_pending');
  assert.equal(plan({ marketDate: day, latest: current, manifest, workflowRuns: [successRun], review: { ...review, marketDate: '2026-11-03' } }).status, 'existing_run_success_publication_pending');
});

test('matching run discovered after manifest PUT suppresses dispatch', () => {
  const result = plan({ marketDate: day, latest, manifest, manifestPutResponse: putSuccess, workflowRunsAfterPut: [successRun] });
  assert.equal(result.status, 'existing_run_success_publication_pending');
  assert.equal(result.action, undefined);
});

function row(state = {}, revision = 4, leaseUntil = 0) {
  return { id: 1, state_json: JSON.stringify(state), revision, lease_until: leaseUntil };
}

test('claim uses a 30-minute lease, returns revision CAS, and resets date-scoped cache and budget', () => {
  const oldManifest = { marketDate: '2026-11-03', stocks: [{ code: 'old' }] };
  const original = row({ marketDate: '2026-11-03', cachedManifest: oldManifest,
    braveUsage: { date: '2026-11-03', used: 8, reserved: 0 } });
  const result = claim(original, { marketDate: day, owner: 'exec-1', now: 10_000 });
  assert.equal(result.status, 'claimed');
  assert.equal(result.expectedRevision, 4);
  assert.equal(result.row.revision, 5);
  assert.equal(result.leaseUntil, 10_000 + 30 * 60 * 1000);
  assert.equal(result.allocatedBrave, 20);
  assert.equal(result.braveUsedBefore, 0);
  assert.equal(result.state.cachedManifest, null);
  assert.deepEqual(result.state.braveUsage, { date: day, used: 0, reserved: 20 });
  assert.equal(JSON.parse(original.state_json).marketDate, '2026-11-03');
});

test('active lease blocks a second worker without changing the row', () => {
  const held = row({ marketDate: day, leaseOwner: 'exec-1' }, 5, 20_000);
  assert.deepEqual(claim(held, { marketDate: day, owner: 'exec-2', now: 10_000 }),
    { status: 'lease_active', leaseUntil: 20_000, expectedRevision: 5 });
});

test('expired crashed reservation counts as spent and cannot replenish daily Brave budget', () => {
  const crashed = row({ marketDate: day, leaseOwner: 'dead-exec',
    braveUsage: { date: day, used: 5, reserved: 15 } }, 8, 9_000);
  const retry = claim(crashed, { marketDate: day, owner: 'exec-retry', now: 10_000 });
  assert.equal(retry.status, 'claimed');
  assert.equal(retry.allocatedBrave, 0);
  assert.equal(retry.braveUsedBefore, 20);
  assert.deepEqual(retry.state.braveUsage, { date: day, used: 20, reserved: 0 });
  assert.equal(retry.state.cachedManifest, null);
});

test('finish records cumulative Brave usage and refunds the unused reservation under CAS', () => {
  const acquired = claim(row(), { marketDate: day, owner: 'exec-1', now: 100 });
  const manifestWithPriorUsage = { marketDate: day, searchUsage: { date: day, brave: 0 }, stocks: [] };
  const done = finish(acquired.row, { marketDate: day, owner: 'exec-1', now: 200,
    actualBraveUsed: 6, manifest: manifestWithPriorUsage });
  assert.equal(done.status, 'finished');
  assert.equal(done.expectedRevision, acquired.row.revision);
  assert.equal(done.row.revision, acquired.row.revision + 1);
  assert.equal(done.state.braveUsage.used, 6);
  assert.equal(done.state.braveUsage.reserved, 0);
  assert.equal(done.state.cachedManifest.searchUsage.brave, 6);
  assert.equal(done.row.lease_until, acquired.leaseUntil);
  assert.equal(done.state.leaseOwner, 'exec-1');
  const next = claim(done.row, { marketDate: day, owner: 'exec-2', now: 300, reserveBrave: true });
  assert.equal(next.status, 'lease_active');
  const released = finish(acquired.row, { marketDate: day, owner: 'exec-1', now: 200,
    actualBraveUsed: 21, manifest: manifestWithPriorUsage });
  assert.equal(released.status, 'brave_usage_invalid');
});

test('normal finish releases unused budget for a later same-day claim and cached manifest retains usage', () => {
  const acquired = claim(row(), { marketDate: day, owner: 'exec-1', now: 1 });
  const completed = finish(acquired.row, { marketDate: day, owner: 'exec-1', now: 2,
    actualBraveUsed: 5, manifest: { marketDate: day, stocks: [] }, releaseLease: true });
  const next = claim(completed.row, { marketDate: day, owner: 'exec-2', now: 3 });
  assert.equal(next.braveUsedBefore, 5);
  assert.equal(next.allocatedBrave, 15);
  assert.equal(next.state.cachedManifest.searchUsage.brave, 5);
});

test('dispatch intent is sticky, requires finished manifest and commit SHA, and later claim is reconciliation only', () => {
  const acquired = claim(row(), { marketDate: day, owner: 'exec-1', now: 1 });
  const completed = finish(acquired.row, { marketDate: day, owner: 'exec-1', now: 2,
    actualBraveUsed: 0, manifest: { marketDate: day, stocks: [] } });
  assert.equal(recordDispatchIntent(completed.row, { marketDate: day, owner: 'wrong', now: 3, manifestCommitSha: commit }).status, 'lease_conflict');
  assert.equal(recordDispatchIntent(completed.row, { marketDate: day, owner: 'exec-1', now: 3, manifestCommitSha: 'bad' }).status, 'dispatch_intent_invalid');
  const intent = recordDispatchIntent(completed.row, { marketDate: day, owner: 'exec-1', now: 3, manifestCommitSha: commit });
  assert.equal(intent.status, 'dispatch_intent_recorded');
  assert.equal(intent.expectedRevision, completed.row.revision);
  assert.equal(intent.row.revision, completed.row.revision + 1);
  assert.equal(recordDispatchIntent(intent.row, { marketDate: day, owner: 'exec-1', now: 4, manifestCommitSha: commit }).status, 'dispatch_intent_exists');
  const recovered = claim({ ...intent.row, lease_until: 3 }, { marketDate: day, owner: 'reconcile', now: 4 });
  assert.equal(recovered.status, 'claimed');
  assert.equal(recovered.reconcileOnly, true);
  assert.equal(recovered.allocatedBrave, 0);
  assert.equal(recovered.state.dispatchIntent.manifestCommitSha, commit);
});

test('claim validates row and configuration and can reserve only the supplied remaining daily budget', () => {
  assert.equal(claim(null, { marketDate: day, owner: 'exec', now: 1 }).status, 'state_invalid');
  assert.equal(claim(row(), { marketDate: day, owner: '', now: 1 }).status, 'configuration_required');
  assert.equal(claim(row(), { marketDate: day, owner: 'exec', now: 1, dailyBraveLimit: 25 }).status, 'configuration_required');
  const limited = claim(row(), { marketDate: day, owner: 'exec', now: 1, dailyBraveLimit: 7 });
  assert.equal(limited.allocatedBudget, 7);
});
