'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const folder = __dirname;
const output = path.join(folder, 'peg-source-discovery.workflow.json');
execFileSync(process.execPath, [path.join(folder, 'build-peg-source-workflow.cjs')]);
const workflow = JSON.parse(fs.readFileSync(output, 'utf8'));
const byName = name => workflow.nodes.find(n => n.name === name);
const targets = (name, branch = 0) => workflow.connections[name]?.main?.[branch] || [];
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

function executeCode(name, incoming, refs = {}, staticData = {}) {
  const code = byName(name).parameters.jsCode;
  const fn = new AsyncFunction('$input', '$', '$getWorkflowStaticData', 'Buffer', code);
  return fn({ first: () => ({ json: incoming }) }, node => ({ first: () => ({ json: refs[node] }), last: () => ({ json: refs[node] }) }), () => staticData, Buffer);
}

test('workflow has manual and passthrough execute triggers and only read-only native HTTP operations', () => {
  assert.equal(workflow.active, false);
  assert.equal(byName('Manual Trigger').typeVersion, 1);
  assert.equal(byName('Execute Workflow Trigger').typeVersion, 1.1);
  assert.equal(byName('Execute Workflow Trigger').parameters.inputSource, 'passthrough');
  assert.ok(targets('Manual Trigger').some(x => x.node === 'Fetch public latest.json'));
  assert.ok(targets('Execute Workflow Trigger').some(x => x.node === 'Fetch public latest.json'));
  for (const n of workflow.nodes.filter(n => n.type.endsWith('.httpRequest'))) {
    assert.equal(n.typeVersion, 4.5);
    assert.equal(n.parameters.method, 'GET');
    assert.equal(n.parameters.options.timeout, 15000);
    assert.equal(n.parameters.options.redirect.redirect.followRedirects, false);
    assert.equal(n.parameters.options.response.response.fullResponse, true);
    assert.equal(n.parameters.options.response.response.neverError, true);
    assert.equal(n.retryOnFail, false);
    assert.equal(n.onError, 'continueRegularOutput');
  }
  assert.equal(byName('Fetch public latest.json').parameters.url, 'https://stockscreener.andyshih.uk/data/latest.json');
  assert.equal(byName('Fetch issuer registry').parameters.url, 'https://api.github.com/repos/pingpongtech-uskg/stock-web-pages/contents/config/peg_issuer_domains.json?ref=main');
  assert.equal(byName('Fetch issuer registry').credentials.githubApi.id, 'F0VoGrfOT4OTl2o8');
  assert.equal(byName('Search with Brave').credentials.braveSearchApi.id, 'keND4ReyUl49IW5p');
  assert.equal(byName('Search with SearxNG').parameters.authentication, 'none');
  assert.equal(workflow.nodes.some(n => /schedule|cron/i.test(n.type)), false);
  assert.equal(workflow.nodes.some(n => n.type.endsWith('.github') || n.parameters.method === 'POST' || n.parameters.method === 'PATCH' || n.parameters.method === 'PUT' || n.parameters.method === 'DELETE'), false);
});

test('all Code nodes compile and embed only the local discovery state machine', () => {
  for (const node of workflow.nodes.filter(n => n.type === 'n8n-nodes-base.code')) {
    assert.doesNotThrow(() => new AsyncFunction('$input', '$', '$getWorkflowStaticData', 'Buffer', node.parameters.jsCode), node.name);
    assert.match(node.parameters.jsCode, /function init\(/);
    assert.match(node.parameters.jsCode, /function plan\(/);
    assert.match(node.parameters.jsCode, /function apply\(/);
    assert.doesNotMatch(node.parameters.jsCode, /require\(['"]https?:/);
  }
});

test('initializer uses latest run lineage and returns configuration_required without calling providers', async () => {
  const latest = { marketDate: '2026-11-03', runId: 'daily-run', stocks: [] };
  const registry = { AAA: { officialDomains: ['alpha.example'] } };
  const refs = {
    'Fetch public latest.json': { body: latest, statusCode: 200 },
    'Fetch issuer registry': { body: { content: Buffer.from(JSON.stringify(registry)).toString('base64') }, statusCode: 200 },
  };
  const staticData = { pegSourceManifest: null, pegSourceUsage: { date: '2026-11-03', brave: 3 } };
  const initialized = await executeCode('Initialize PEG source discovery', {}, refs, staticData);
  assert.equal(initialized[0].json.state.config.requestId, 'peg-2026-11-03-daily-run');
  assert.equal(initialized[0].json.state.config.searxBaseUrl, '');
  assert.equal(initialized[0].json.state.outcome, 'configuration_required');
  assert.equal(initialized[0].json.state.braveUsed, 3);
  const planned = await executeCode('Plan next provider', initialized[0].json, {}, staticData);
  assert.equal(planned[0].json.done, true);
  assert.equal(planned[0].json.outcome, 'configuration_required');
  assert.equal(planned[0].json.state.manifest.stocks.length, 0);
  assert.equal(staticData.pegSourceManifest, null);
  assert.equal(staticData.pegSourceUsage.brave, 3);
  const skipped = await executeCode('Finish PEG manifest', planned[0].json, {}, staticData);
  assert.equal(skipped[0].json.outcome, 'configuration_required');
  assert.match(skipped[0].json.message, /SearxNG base URL is not configured/);
  assert.equal(skipped[0].json.stocks.length, 0);
  assert.equal(staticData.pegSourceUsage.brave, 3);
});

test('provider apply uses last Plan state, preserves HTTP diagnostics, then loops back to Plan', () => {
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
  assert.ok(targets('Finish PEG manifest').length === 0);
});

test('VM Plan and Apply Code nodes execute Searx response path without network or state loss', async () => {
  const state = {
    config: { searxBaseUrl: 'https://search.example/search', marketDate: '2026-11-03', requestId: 'peg-2026-11-03-run', braveDailyLimit: 20 },
    cursor: 0, stocks: [{ code: 'AAA', name: 'Alpha', legalName: 'Alpha Corp', period: '2026Q3', domains: ['alpha.example'], results: null, reason: null, nextProvider: 'searx' }],
    pending: null, unavailable: {}, attempts: {}, outcome: null, manifest: null, braveUsed: 0,
  };
  const planned = await executeCode('Plan next provider', { state });
  assert.equal(planned[0].json.action.provider, 'searx');
  assert.match(planned[0].json.action.url, /^https:\/\/search\.example\/search\?/);
  const applied = await executeCode('Apply provider response', { statusCode: 200, body: { results: [{ url: 'https://alpha.example/investors/q3.pdf', title: 'Quarterly financial report' }] }, headers: {} }, { 'Plan next provider': planned[0].json });
  assert.equal(applied[0].json.stocks[0].results[0].provider, 'searx');
  const done = await executeCode('Plan next provider', applied[0].json);
  assert.equal(done[0].json.done, true);
  const staticData = {};
  const finished = await executeCode('Finish PEG manifest', done[0].json, {}, staticData);
  assert.equal(finished[0].json.outcome, 'complete');
  assert.equal(finished[0].json.stocks[0].results.length, 1);
  assert.equal(staticData.pegSourceManifest.stocks[0].results.length, 1);
  assert.equal(staticData.pegSourceUsage.brave, 0);
});
