'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const folder = __dirname;
const output = path.join(folder, 'peg-source-discovery.workflow.json');
execFileSync(process.execPath, [path.join(folder, 'build-peg-source-workflow.cjs')]);
const workflow = JSON.parse(fs.readFileSync(output, 'utf8'));
const byName = name => workflow.nodes.find(n => n.name === name);
const targets = (name, branch = 0) => workflow.connections[name]?.main?.[branch] || [];
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const owner = 'qa-1';

function executeCode(name, input, refs = {}, executionId = owner) {
  const fn = new AsyncFunction('$input', '$', '$getWorkflowStaticData', 'Buffer', '$execution', byName(name).parameters.jsCode);
  const items = Array.isArray(input) ? input.map(json => ({ json })) : [{ json: input }];
  const reference = node => {
    const raw = refs[node];
    const values = raw === undefined ? [] : Array.isArray(raw) ? raw : [raw];
    return {
      first: () => values.length ? { json: values[0] } : undefined,
      last: () => values.length ? { json: values[values.length - 1] } : undefined,
      all: () => values.map(json => ({ json })),
      isExecuted: Object.hasOwn(refs, node),
    };
  };
  return fn({ first: () => items[0], all: () => items }, reference, () => ({}), Buffer, { id: executionId });
}
function row(state = {}, revision = 0, leaseUntil = 0) {
  return { id: 1, revision, lease_until: leaseUntil, searx_url: 'http://searxng:8080', state_json: JSON.stringify(state) };
}
function publicLatest(marketDate = '2026-11-03', runId = 'daily-run', stocks = [{ code: 'AAA', name: 'Alpha', pegReview: { status: 'needs_review' } }]) {
  return { statusCode: 200, body: { marketDate, runId, stocks } };
}
function registryResponse() {
  const issuers = { AAA: { legalName: 'Alpha Corp', officialDomains: ['alpha.example'] } };
  return { statusCode: 200, body: { content: Buffer.from(JSON.stringify(issuers)).toString('base64') } };
}
function leaseRow(marketDate = '2026-11-03', used = 0, reserved = 20) {
  return row({ marketDate, requestId: `peg-${marketDate}-ttm-v1`, leaseOwner: owner, leaseBraveReservation: reserved,
    braveUsage: { date: marketDate, used, reserved }, cachedManifest: null }, 4, Date.now() + 60_000);
}

const latestUrl = 'https://stockscreener.andyshih.uk/data/latest.json';
const issuerUrl = 'https://api.github.com/repos/pingpongtech-uskg/stock-web-pages/contents/config/peg_issuer_domains.json?ref=main';

test('workflow keeps manual and passthrough triggers and bounds native read/write operations', () => {
  assert.equal(workflow.active, false);
  assert.equal(byName('Manual Trigger').typeVersion, 1);
  assert.equal(byName('Execute Workflow Trigger').typeVersion, 1.1);
  assert.equal(byName('Execute Workflow Trigger').parameters.inputSource, 'passthrough');
  assert.ok(targets('Manual Trigger').some(x => x.node === 'Fetch public latest.json'));
  assert.ok(targets('Execute Workflow Trigger').some(x => x.node === 'Fetch public latest.json'));
  assert.ok(targets('Fetch public latest.json').some(x => x.node === 'Read durable PEG progress'));
  assert.ok(targets('Verify discovery lease').some(x => x.node === 'Fetch issuer registry'));
  const http = workflow.nodes.filter(n => n.type.endsWith('.httpRequest'));
  const writes = http.filter(n => n.parameters.method !== 'GET');
  assert.deepEqual(writes.map(n => [n.name, n.parameters.method, n.parameters.url]), [
    ['Commit approved source manifest', 'PUT', 'https://api.github.com/repos/pingpongtech-uskg/stock-web-pages/contents/config/peg_search_results.json'],
    ['Dispatch PEG enrichment once', 'POST', 'https://api.github.com/repos/pingpongtech-uskg/stock-web-pages/actions/workflows/peg.yml/dispatches'],
  ]);
  for (const n of http) {
    assert.equal(n.typeVersion, 4.5);
    assert.equal(n.parameters.options.timeout, 15000);
    assert.equal(n.parameters.options.redirect.redirect.followRedirects, false);
    assert.equal(n.parameters.options.response.response.fullResponse, true);
    assert.equal(n.parameters.options.response.response.neverError, true);
    assert.equal(n.retryOnFail, false);
    assert.equal(n.onError, 'continueRegularOutput');
  }
  for (const name of ['Commit approved source manifest', 'Dispatch PEG enrichment once']) {
    const node = byName(name);
    assert.equal(node.parameters.sendBody, true);
    assert.equal(node.parameters.authentication, 'predefinedCredentialType');
    assert.equal(node.credentials.githubApi.id, 'F0VoGrfOT4OTl2o8');
  }
  assert.equal(byName('Fetch public latest.json').parameters.url, latestUrl);
  assert.equal(byName('Fetch issuer registry').parameters.url, issuerUrl);
  assert.equal(byName('Search with Brave').credentials.braveSearchApi.id, 'keND4ReyUl49IW5p');
  assert.equal(byName('Search with Brave').parameters.headerParameters.parameters.find(h => h.name === 'Accept').value, 'application/json');
  assert.equal(byName('Search with SearxNG').parameters.authentication, 'none');
  assert.equal(workflow.nodes.some(n => /schedule|cron|openai|anthropic|llm/i.test(n.type + n.name)), false);
});

test('every Code node compiles, and embedded source contains no credentials or AI calls', () => {
  for (const node of workflow.nodes.filter(n => n.type === 'n8n-nodes-base.code')) {
    assert.doesNotThrow(() => new AsyncFunction('$input', '$', '$getWorkflowStaticData', 'Buffer', '$execution', node.parameters.jsCode), node.name);
    assert.doesNotMatch(node.parameters.jsCode, /gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{20,}|sk-[A-Za-z0-9]{20,}/i, node.name);
  }
  for (const name of ['Initialize PEG source discovery', 'Plan next provider', 'Apply provider response']) {
    const code = byName(name).parameters.jsCode;
    assert.match(code, /function init\(/);
    assert.match(code, /function plan\(/);
    assert.match(code, /function apply\(/);
  }
  assert.doesNotMatch(byName('Finish PEG manifest').parameters.jsCode, /staticData|dataTable|fetch\(/i);
});

test('initializer uses latest market date, deterministic request ID, and verified durable cache state', async () => {
  const date = '2026-11-03';
  const verified = leaseRow(date, 3, 17);
  const refs = {
    'Fetch public latest.json': publicLatest(date, 'release-run-rotates'),
    'Fetch issuer registry': registryResponse(),
    'Verify discovery lease': verified,
  };
  const initialized = await executeCode('Initialize PEG source discovery', {}, refs);
  const state = initialized[0].json.state;
  assert.equal(state.config.requestId, 'peg-2026-11-03-ttm-v1');
  assert.equal(state.config.marketDate, date);
  assert.equal(state.config.searxBaseUrl, 'http://searxng:8080');
  assert.equal(state.braveUsed, 3);
  const planned = await executeCode('Plan next provider', initialized[0].json);
  assert.equal(planned[0].json.done, false);
  assert.equal(planned[0].json.action.provider, 'searx');
  assert.match(planned[0].json.action.url, /^http:\/\/searxng:8080\/search\?/);
  assert.equal(planned[0].json.state.config.marketDate, date);
});

test('provider branches apply the last Plan state and loop to Plan with response headers and status', () => {
  assert.ok(targets('Discovery complete?', 0).some(x => x.node === 'Finish PEG manifest'));
  assert.ok(targets('Discovery complete?', 1).some(x => x.node === 'Use SearxNG?'));
  assert.ok(targets('Use SearxNG?', 0).some(x => x.node === 'Search with SearxNG'));
  assert.ok(targets('Use SearxNG?', 1).some(x => x.node === 'Search with Brave'));
  assert.ok(targets('Search with SearxNG').some(x => x.node === 'Apply provider response'));
  assert.ok(targets('Search with Brave').some(x => x.node === 'Apply provider response'));
  assert.ok(targets('Apply provider response').some(x => x.node === 'Plan next provider'));
  const applyCode = byName('Apply provider response').parameters.jsCode;
  assert.match(applyCode, /\$\('Plan next provider'\)\.last\(\)\.json/);
  assert.match(applyCode, /planned\.state/);
  assert.match(applyCode, /headers/);
  assert.match(applyCode, /statusCode/);
});

test('VM Plan and Apply preserve a Searx result through manifest preparation and durable finish', async () => {
  const date = '2026-11-03';
  const verified = leaseRow(date, 2, 18);
  const latest = publicLatest(date);
  const initialized = await executeCode('Initialize PEG source discovery', {}, {
    'Fetch public latest.json': latest,
    'Fetch issuer registry': registryResponse(),
    'Verify discovery lease': verified,
  });
  const planned = await executeCode('Plan next provider', initialized[0].json);
  assert.equal(planned[0].json.action.provider, 'searx');
  const applied = await executeCode('Apply provider response', {
    statusCode: 200,
    body: { results: [{ url: 'https://alpha.example/investors/q3.pdf', title: 'Quarterly financial report' }] },
    headers: { 'retry-after': '7' },
  }, { 'Plan next provider': planned[0].json });
  assert.equal(applied[0].json.stocks[0].results[0].provider, 'searx');
  const done = await executeCode('Plan next provider', applied[0].json);
  assert.equal(done[0].json.done, true);
  const manifest = (await executeCode('Finish PEG manifest', done[0].json))[0].json;
  assert.equal(manifest.stocks[0].results.length, 1);
  assert.equal(manifest.requestId, 'peg-2026-11-03-ttm-v1');
  const saved = await executeCode('Prepare durable search results', manifest, { 'Verify discovery lease': verified });
  assert.equal(saved[0].json.status, 'finished');
  assert.equal(saved[0].json.state.cachedManifest.stocks[0].results.length, 1);
  assert.equal(saved[0].json.state.braveUsage.used, 2);
  assert.equal(saved[0].json.state.braveUsage.reserved, 0);
  assert.equal(saved[0].json.state.leaseOwner, owner);
});

test('VM lease claim reserves bounded Brave quota and finish accepts only the owned live lease', async () => {
  const date = '2026-11-03';
  const initial = row({ marketDate: date, braveUsage: { date, used: 5, reserved: 0 }, cachedManifest: null }, 7, 0);
  const latest = publicLatest(date);
  const claim = (await executeCode('Prepare discovery lease', initial, { 'Fetch public latest.json': latest }))[0].json;
  assert.equal(claim.status, 'claimed');
  assert.equal(claim.claimReady, true);
  assert.equal(claim.state.braveUsage.used, 5);
  assert.equal(claim.allocatedBudget, 15);
  assert.equal(claim.expectedRevision, 7);
  const verify = (await executeCode('Verify discovery lease', claim.row))[0].json;
  assert.equal(verify.revision, 8);
  assert.equal(JSON.parse(verify.state_json).leaseOwner, owner);

  const finishedManifest = { marketDate: date, requestId: `peg-${date}-ttm-v1`, searchUsage: { date, brave: 6 }, stocks: [] };
  const finished = (await executeCode('Prepare durable search results', finishedManifest, { 'Verify discovery lease': verify }))[0].json;
  assert.equal(finished.status, 'finished');
  assert.equal(finished.expectedRevision, verify.revision);
  assert.equal(finished.state.braveUsage.used, 6);
  assert.equal(finished.state.braveUsage.reserved, 0);
  assert.equal(JSON.parse(finished.row.state_json).cachedManifest.searchUsage.brave, 6);

  const stale = await executeCode('Prepare durable search results', finishedManifest, { 'Verify discovery lease': row(JSON.parse(verify.state_json), verify.revision, Date.now() - 1) });
  assert.equal(stale[0].json.outcome, 'lease_conflict');
});

test('blank durable Searx endpoint stops before claiming a lease or reaching either provider', async () => {
  const input = row({}, 0, 0);
  input.searx_url = '';
  const prepared = (await executeCode('Prepare discovery lease', input, { 'Fetch public latest.json': publicLatest() }))[0].json;
  assert.equal(prepared.outcome, 'configuration_required');
  assert.equal(prepared.claimReady, false);
  const wrongDate = await executeCode('Prepare discovery lease', row({}, 0, 0), {
    'Fetch public latest.json': publicLatest('2026-11-03'),
    'Execute Workflow Trigger': { marketDate: '2026-11-02' },
  });
  assert.equal(wrongDate[0].json.outcome, 'public_date_pending');
  assert.equal(wrongDate[0].json.claimReady, undefined);
  assert.equal(targets('Discovery lease available?', 0).some(x => x.node === 'Claim PEG progress with CAS'), true);
  assert.equal(targets('Discovery lease available?', 1).some(x => x.node === 'Show PEG recovery outcome'), true);
  assert.equal(targets('Fetch public latest.json').some(x => x.node === 'Read durable PEG progress'), true);
  assert.equal(targets('Verify discovery lease').some(x => x.node === 'Fetch issuer registry'), true);
  assert.equal(byName('Search with Brave').parameters.url, '={{ $json.action.url }}');
  assert.equal(byName('Search with SearxNG').parameters.url, '={{ $json.action.url }}');
});

test('duplicate existing PEG Actions request suppresses search and recognizes completed publication', async () => {
  const date = '2026-11-03';
  const requestId = `peg-${date}-ttm-v1`;
  const latest = publicLatest(date, 'daily-run');
  const run = { id: 981, display_title: `PEG repair | ${requestId} | ${date}`, status: 'completed', conclusion: 'success', html_url: 'https://github.com/example/run/981' };
  const rowValue = row({ marketDate: date, requestId, leaseOwner: owner, cachedManifest: null, braveUsage: { date, used: 4, reserved: 16 } }, 11, Date.now() + 30_000);
  const runList = { statusCode: 200, body: { workflow_runs: [run] } };
  const check = (await executeCode('Check existing PEG request', runList, { 'Verify discovery lease': rowValue }))[0].json;
  assert.equal(check.searchRequired, false);
  assert.equal(check.outcome, 'existing_request');
  const publication = (await executeCode('Evaluate existing PEG publication', { marketDate: date, requestId, runId: 'daily-run' }, {
    'Verify discovery lease': rowValue,
    'Fetch public latest.json': latest,
    'Read exact PEG Actions requests': runList,
    'Check existing PEG request': check,
  }))[0].json;
  assert.equal(publication.outcome, 'publication_complete');
  assert.equal(publication.run.id, '981');
  assert.equal(targets('Search required?', 0).some(x => x.node === 'Initialize PEG source discovery'), true);
  assert.equal(targets('Search required?', 1).some(x => x.node === 'Read public PEG publication proof'), true);
});

test('all Data Table updates require row ID and expected revision, and manifest replacement uses its returned SHA', async () => {
  const updates = workflow.nodes.filter(n => n.type === 'n8n-nodes-base.dataTable' && n.parameters.operation === 'update');
  assert.ok(updates.length >= 4);
  for (const node of updates) {
    assert.equal(node.parameters.matchType, 'allConditions', node.name);
    const conditions = node.parameters.filters.conditions;
    assert.ok(conditions.some(c => c.keyName === 'id' && c.condition === 'eq' && c.keyValue === '1'), node.name);
    assert.ok(conditions.some(c => c.keyName === 'revision' && c.condition === 'eq' && c.keyValue === '={{ $json.expectedRevision }}'), node.name);
  }
  const date = '2026-11-03';
  const persisted = row({ marketDate: date, requestId: `peg-${date}-ttm-v1`, leaseOwner: owner,
    cachedManifest: { marketDate: date, stocks: [] }, braveUsage: { date, used: 0, reserved: 20 } }, 12, Date.now() + 30_000);
  const latest = publicLatest(date);
  const runs = { statusCode: 200, body: { workflow_runs: [] } };
  const put = (await executeCode('Prepare source manifest commit', { statusCode: 200, body: { sha: 'a'.repeat(40) } }, {
    'Persist search results with CAS': persisted,
    'Fetch public latest.json': latest,
    'Read exact PEG Actions requests': runs,
  }))[0].json;
  assert.equal(put.status, 'manifest_publish_ready');
  assert.equal(put.body.sha, 'a'.repeat(40));
  assert.equal(put.body.branch, 'main');
  const create = (await executeCode('Prepare source manifest commit', { statusCode: 404, body: {} }, {
    'Persist search results with CAS': persisted,
    'Fetch public latest.json': latest,
    'Read exact PEG Actions requests': runs,
  }))[0].json;
  assert.equal(create.status, 'manifest_publish_ready');
  assert.equal(Object.hasOwn(create.body, 'sha'), false);
});
