'use strict';

const MANIFEST_PATH = 'config/peg_search_results.json';
const REPOSITORY = 'pingpongtech-uskg/stock-web-pages';
const WORKFLOW_PATH = 'peg.yml';

function validDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1];
}

function requestIdFor(marketDate) {
  if (!validDate(marketDate)) throw new Error('peg_market_date');
  return `peg-${marketDate}-ttm-v1`;
}

function stableValue(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('peg_manifest_json');
    return value;
  }
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== 'object') throw new Error('peg_manifest_json');
  const result = {};
  for (const key of Object.keys(value).sort()) result[key] = stableValue(value[key]);
  return result;
}

function unwrap(value) {
  if (!value || typeof value !== 'object') return value;
  if (Number.isInteger(value.statusCode) && Object.prototype.hasOwnProperty.call(value, 'body')) {
    let body = value.body;
    if (typeof body === 'string') {
      try { body = JSON.parse(body); } catch { return { statusCode: value.statusCode, body: null }; }
    }
    return { ...value, body };
  }
  return value;
}

function matchingRuns(value, requestId) {
  const source = Array.isArray(value) ? value : Array.isArray(value?.workflow_runs) ? value.workflow_runs : [];
  return source.filter(run => {
    if (!run || typeof run !== 'object') return false;
    if (run.requestId === requestId || run.request_id === requestId) return true;
    const title = run.display_title || run.name || run.title || '';
    return title === `PEG repair | ${requestId} | ${requestId.slice(4, 14)}`;
  }).slice().sort((a, b) => Number(b.id || 0) - Number(a.id || 0));
}

function runState(run, latest, review, marketDate, requestId) {
  const summary = {
    id: run.id == null ? null : String(run.id),
    status: typeof run.status === 'string' ? run.status : 'unknown',
    conclusion: typeof run.conclusion === 'string' ? run.conclusion : null,
    url: typeof run.html_url === 'string' ? run.html_url : null,
  };
  if (run.status !== 'completed') return { status: 'existing_run_pending', run: summary };
  if (run.conclusion !== 'success') return { status: 'existing_run_failed', run: summary };
  const current = unwrap(latest);
  const publicReview = unwrap(review);
  const latestValue = current?.body && current.statusCode ? current.body : current;
  const reviewValue = publicReview?.body && publicReview.statusCode ? publicReview.body : publicReview;
  const complete = latestValue?.marketDate === marketDate &&
    reviewValue?.marketDate === marketDate && reviewValue?.requestId === requestId &&
    typeof reviewValue?.runId === 'string' && reviewValue.runId === latestValue?.runId;
  return complete
    ? { status: 'publication_complete', run: summary, runId: reviewValue.runId }
    : { status: 'existing_run_success_publication_pending', run: summary };
}

function sourceFatal(manifest) {
  return manifest.fatal === true || manifest.providerSearchFatal === true ||
    ['configuration_required', 'provider_search_fatal'].includes(manifest.outcome) ||
    manifest.searchStatus === 'fatal';
}

function baseValidation(input) {
  const marketDate = input?.marketDate;
  const requestId = requestIdFor(marketDate);
  const latest = unwrap(input.latest);
  const latestValue = latest?.body && latest.statusCode ? latest.body : latest;
  if (!latestValue || latestValue.marketDate !== marketDate) return { result: { status: 'stale_public', requestId } };
  const manifest = input.manifest;
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) return { result: { status: 'manifest_invalid', requestId } };
  if (manifest.marketDate !== marketDate) return { result: { status: 'manifest_date_mismatch', requestId } };
  if (!Array.isArray(manifest.stocks)) return { result: { status: 'manifest_invalid', requestId } };
  if (sourceFatal(manifest)) return { result: { status: 'source_search_fatal', requestId } };
  return { marketDate, requestId, latest: latestValue, manifest };
}

function plan(input = {}) {
  let validated;
  try { validated = baseValidation(input); }
  catch (error) { return { status: 'configuration_required', reason: error.message === 'peg_market_date' ? 'invalid_market_date' : 'invalid_input' }; }
  if (validated.result) return validated.result;
  const { marketDate, requestId, manifest } = validated;
  const runs = matchingRuns(input.workflowRuns, requestId);
  if (runs.length) return { ...runState(runs[0], validated.latest, input.review, marketDate, requestId), requestId };

  if (input.manifestPutResponse !== undefined) {
    const put = unwrap(input.manifestPutResponse);
    const statusCode = Number(put?.statusCode || 0);
    const commitSha = put?.body?.commit?.sha;
    if (statusCode < 200 || statusCode >= 300 || typeof commitSha !== 'string' || !/^[a-f0-9]{40}$/.test(commitSha)) {
      return { status: 'manifest_publish_failed', requestId };
    }
    const secondCheck = matchingRuns(input.workflowRunsAfterPut, requestId);
    if (secondCheck.length) return { ...runState(secondCheck[0], validated.latest, input.review, marketDate, requestId), requestId };
    return {
      status: 'dispatch_ready', requestId, manifestCommitSha: commitSha,
      action: {
        method: 'POST', path: `/repos/${REPOSITORY}/actions/workflows/${WORKFLOW_PATH}/dispatches`,
        body: { ref: 'main', inputs: { market_date: marketDate, request_id: requestId, search_manifest_commit: commitSha } },
      },
    };
  }

  const existing = unwrap(input.contentsResponse);
  const contentsStatus = Number(existing?.statusCode || 0);
  let expectedSha;
  if (contentsStatus === 404) expectedSha = null;
  else if (contentsStatus === 200 && typeof existing?.body?.sha === 'string' && /^[a-f0-9]{40}$/.test(existing.body.sha)) expectedSha = existing.body.sha;
  else return { status: 'manifest_contents_unavailable', requestId };

  const publishedManifest = { ...manifest, marketDate, requestId };
  let content;
  try { content = `${JSON.stringify(stableValue(publishedManifest))}\n`; }
  catch { return { status: 'manifest_invalid', requestId }; }
  return {
    status: 'manifest_publish_ready', requestId, path: MANIFEST_PATH,
    content, expectedSha,
    message: `data: update PEG search results for ${marketDate}`,
  };
}

const LEASE_MS = 30 * 60 * 1000;
const DEFAULT_DAILY_BRAVE_LIMIT = 20;

function readRow(row) {
  if (!row || row.id !== 1 || !Number.isSafeInteger(row.revision) || row.revision < 0 ||
      !Number.isFinite(Number(row.lease_until))) return null;
  let state;
  try { state = row.state_json ? JSON.parse(row.state_json) : {}; } catch { return null; }
  if (!state || typeof state !== 'object' || Array.isArray(state)) return null;
  return state;
}

function nextRow(row, state, leaseUntil) {
  return {
    id: 1,
    state_json: JSON.stringify(state),
    revision: row.revision + 1,
    lease_until: leaseUntil,
  };
}

function claim(row, { marketDate, owner, now, dailyBraveLimit = DEFAULT_DAILY_BRAVE_LIMIT, reserveBrave = true } = {}) {
  let requestId;
  try { requestId = requestIdFor(marketDate); } catch { return { status: 'configuration_required', reason: 'invalid_market_date' }; }
  if (typeof owner !== 'string' || !/^[A-Za-z0-9_.:-]{1,160}$/.test(owner) || !Number.isSafeInteger(now) || now < 0 ||
      !Number.isInteger(dailyBraveLimit) || dailyBraveLimit < 0 || dailyBraveLimit > DEFAULT_DAILY_BRAVE_LIMIT) {
    return { status: 'configuration_required', reason: 'invalid_claim' };
  }
  const prior = readRow(row);
  if (!prior) return { status: 'state_invalid' };
  if (Number(row.lease_until) > now) return { status: 'lease_active', leaseUntil: Number(row.lease_until), expectedRevision: row.revision };

  const sameDate = prior.marketDate === marketDate;
  let cachedManifest = sameDate && prior.cachedManifest?.marketDate === marketDate ? prior.cachedManifest : null;
  const priorUsage = sameDate && prior.braveUsage?.date === marketDate ? prior.braveUsage : null;
  let used = Number.isInteger(priorUsage?.used) && priorUsage.used >= 0 ? priorUsage.used : 0;
  let reserved = Number.isInteger(priorUsage?.reserved) && priorUsage.reserved >= 0 ? priorUsage.reserved : 0;
  // A reservation left by an expired lease belongs to a crashed worker; count
  // it as spent so reclaiming the row can never replenish that day's budget.
  if (reserved > 0) { used += reserved; reserved = 0; }
  if (cachedManifest) {
    cachedManifest = {
      ...cachedManifest,
      searchUsage: { ...(cachedManifest.searchUsage || {}), date: marketDate, brave: used },
    };
  }
  const dispatchIntent = sameDate && prior.dispatchIntent ? prior.dispatchIntent : null;
  const reconcileOnly = Boolean(dispatchIntent);
  const allocatedBudget = reserveBrave && !reconcileOnly
    ? Math.max(0, dailyBraveLimit - used - reserved)
    : 0;
  const state = {
    ...(sameDate ? prior : {}),
    marketDate,
    requestId,
    cachedManifest,
    braveUsage: { date: marketDate, used, reserved: reserved + allocatedBudget },
    dispatchIntent,
    leaseOwner: owner,
    leaseStartedAt: now,
    leaseBraveReservation: allocatedBudget,
    reconcileOnly,
  };
  const leaseUntil = now + LEASE_MS;
  const updated = nextRow(row, state, leaseUntil);
  return { status: 'claimed', expectedRevision: row.revision, row: updated, state,
    allocatedBudget, allocatedBrave: allocatedBudget, braveUsedBefore: used, leaseUntil, reconcileOnly };
}

function finish(row, { marketDate, owner, now, actualBraveUsed, manifest, releaseLease = false } = {}) {
  const prior = readRow(row);
  if (!prior) return { status: 'state_invalid' };
  if (!Number.isSafeInteger(now) || now < 0 || typeof owner !== 'string') return { status: 'configuration_required', reason: 'invalid_finish' };
  if (prior.marketDate !== marketDate || prior.leaseOwner !== owner || Number(row.lease_until) <= now) return { status: 'lease_conflict', expectedRevision: row.revision };
  const usageBefore = prior.braveUsage?.date === marketDate ? prior.braveUsage.used : 0;
  const reservation = prior.leaseBraveReservation || 0;
  if (!Number.isInteger(usageBefore) || usageBefore < 0 || usageBefore > DEFAULT_DAILY_BRAVE_LIMIT ||
      !Number.isInteger(reservation) || reservation < 0 || usageBefore + reservation > DEFAULT_DAILY_BRAVE_LIMIT ||
      !Number.isInteger(actualBraveUsed) || actualBraveUsed < usageBefore || actualBraveUsed > usageBefore + reservation) {
    return { status: 'brave_usage_invalid', expectedRevision: row.revision };
  }
  if (!manifest || typeof manifest !== 'object' || manifest.marketDate !== marketDate || !Array.isArray(manifest.stocks)) {
    return { status: 'manifest_invalid', expectedRevision: row.revision };
  }
  const usage = prior.braveUsage?.date === marketDate ? prior.braveUsage : { date: marketDate, used: 0, reserved: 0 };
  const finishedManifest = {
    ...manifest,
    searchUsage: { ...(manifest.searchUsage || {}), date: marketDate, brave: actualBraveUsed },
  };
  const state = {
    ...prior,
    cachedManifest: finishedManifest,
    braveUsage: {
      date: marketDate,
      used: actualBraveUsed,
      reserved: Math.max(0, usage.reserved - reservation),
    },
    leaseBraveReservation: 0,
    searchFinishedAt: now,
    ...(releaseLease ? { leaseOwner: null } : {}),
  };
  const leaseUntil = releaseLease ? 0 : Number(row.lease_until);
  return { status: 'finished', expectedRevision: row.revision, row: nextRow(row, state, leaseUntil), state, leaseUntil };
}

function recordDispatchIntent(row, { marketDate, owner, now, manifestCommitSha } = {}) {
  const prior = readRow(row);
  if (!prior) return { status: 'state_invalid' };
  if (!Number.isSafeInteger(now) || now < 0 || typeof owner !== 'string') return { status: 'configuration_required', reason: 'invalid_dispatch_intent' };
  if (prior.marketDate !== marketDate || prior.leaseOwner !== owner || Number(row.lease_until) <= now) return { status: 'lease_conflict', expectedRevision: row.revision };
  if (prior.dispatchIntent) return { status: 'dispatch_intent_exists', expectedRevision: row.revision, intent: prior.dispatchIntent };
  if (!validDate(marketDate) || prior.cachedManifest?.marketDate !== marketDate ||
      typeof manifestCommitSha !== 'string' || !/^[a-f0-9]{40}$/.test(manifestCommitSha)) {
    return { status: 'dispatch_intent_invalid', expectedRevision: row.revision };
  }
  const intent = { marketDate, requestId: requestIdFor(marketDate), manifestCommitSha, createdAt: now };
  const state = { ...prior, dispatchIntent: intent };
  return { status: 'dispatch_intent_recorded', expectedRevision: row.revision, row: nextRow(row, state, Number(row.lease_until)), intent };
}

module.exports = { validDate, requestIdFor, plan, claim, finish, recordDispatchIntent };
