'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { init, plan, apply } = require('./peg-source-discovery.cjs');
const cfg = { searxBaseUrl: 'http://searxng:8080', braveDailyLimit: 20, marketDate: '2026-11-03', requestId: 'r1', bootstrapCandidates: [{ code: 'AAA', name: 'Alpha' }] };
const issuer = { AAA: { legalName: 'Alpha Corp', officialDomains: ['alpha.example'], website: 'https://alpha.example' } };
const url = 'https://alpha.example/investors/q3-2026-results.pdf';
const searxHit = { statusCode: 200, body: { results: [{ url, title: 'Q3 financial results' }] } };
function cycle(s, hit = searxHit) { let p = plan(s, '2026-11-03T12:00:00Z'); assert.equal(p.action.provider, 'searx'); return apply(p.state, 'searx', hit, '2026-11-03T12:00:01Z'); }

test('Searx success needs no fallback and filters to normalized financial URLs', () => { const s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, config: cfg }, '2026-11-03T12:00:00Z'); const n = cycle(s); const done = plan(n, '2026-11-03T12:01:00Z'); assert.equal(done.state.manifest.stocks[0].results[0].provider, 'searx'); assert.equal(done.done, true); });
test('failed Searx response falls back once to Brave', () => { let s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, config: cfg }, '2026-11-03T12:00:00Z'); let p = plan(s, '2026-11-03T12:00:00Z'); s = apply(p.state, 'searx', { statusCode: 500, body: {} }, '2026-11-03T12:00:01Z'); p = plan(s, '2026-11-03T12:00:02Z'); assert.equal(p.action.provider, 'brave'); s = apply(p.state, 'brave', { statusCode: 200, body: { web: { results: [{ url, title: 'Investor financial report' }] } } }, '2026-11-03T12:00:03Z'); assert.equal(plan(s, '2026-11-03T12:00:04Z').state.manifest.stocks[0].results[0].provider, 'brave'); });
test('Brave budget exhaustion leaves explicit reason and no action', () => { const s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, config: { ...cfg, braveDailyLimit: 0 } }, '2026-11-03T12:00:00Z'); let p = plan(s, '2026-11-03T12:00:00Z'); let n = apply(p.state, 'searx', { statusCode: 500 }, '2026-11-03T12:00:01Z'); p = plan(n, '2026-11-03T12:00:02Z'); assert.equal(p.done, true); assert.equal(p.state.manifest.stocks[0].reason, 'budget_exhausted'); });
test('same-day cached manifest is reused within 24h', () => { const cachedManifest = { marketDate: cfg.marketDate, generatedAt: '2026-11-03T00:00:00Z', stocks: [{ code: 'AAA', results: [] }] }; const s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, cachedManifest, config: cfg }, '2026-11-03T01:00:00Z'); assert.equal(plan(s, '2026-11-03T01:00:00Z').done, true); assert.equal(plan(s, '2026-11-03T01:00:00Z').state.manifest.stocks[0].reason, undefined); });
test('expired cached manifest is searched', () => { const cachedManifest = { marketDate: cfg.marketDate, generatedAt: '2026-11-01T00:00:00Z', stocks: [] }; const s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, cachedManifest, config: cfg }, '2026-11-03T01:00:00Z'); assert.equal(plan(s, '2026-11-03T01:00:00Z').action.provider, 'searx'); });
test('429 cools provider down and skips repeat calls for remaining stock batch', () => { const latest = { marketDate: cfg.marketDate, stocks: ['AAA','BBB'].map(code => ({ code, name: code, pegReview: 'needs_review' })) }; const s = init({ latest, issuers: { ...issuer, BBB: { officialDomains: ['beta.example'] } }, config: cfg }, '2026-11-03T12:00:00Z'); const p = plan(s, '2026-11-03T12:00:00Z'); const n = apply(p.state, 'searx', { statusCode: 429, headers: { 'retry-after': '120' } }, '2026-11-03T12:00:01Z'); assert.equal(plan(n, '2026-11-03T12:00:02Z').action.provider, 'brave'); });
test('unapproved-domain result is rejected', () => { let s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, config: cfg }, '2026-11-03T12:00:00Z'); const p = plan(s, '2026-11-03T12:00:00Z'); s = apply(p.state, 'searx', { statusCode: 200, body: { results: [{ url: 'https://evil.example/report.pdf', title: 'financial results' }] } }, '2026-11-03T12:00:01Z'); assert.equal(plan(s, '2026-11-03T12:00:02Z').action.provider, 'brave'); });
test('configuration without Searx base URL never calls Brave', () => { const s = init({ latest: {}, issuers: {}, config: { marketDate: cfg.marketDate, requestId: 'x' } }, '2026-11-03T12:00:00Z'); const p = plan(s, '2026-11-03T12:00:00Z'); assert.equal(p.done, true); assert.equal(p.state.outcome, 'configuration_required'); });
test('unfinished state resumes at pending action', () => { const s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, config: cfg }, '2026-11-03T12:00:00Z'); const p = plan(s, '2026-11-03T12:00:00Z'); assert.equal(plan(p.state, '2026-11-03T12:00:01Z').action.url, p.action.url); });
test('stocks outside needs_review are skipped', () => { const s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'not_applicable' }] }, issuers: issuer, config: cfg }, '2026-11-03T12:00:00Z'); assert.equal(plan(s, '2026-11-03T12:00:00Z').done, true); assert.equal(plan(s, '2026-11-03T12:00:00Z').state.manifest.stocks.length, 0); });
test('bootstrap candidates used only when current latest market date and review absent', () => { const s = init({ latest: { marketDate: cfg.marketDate, stocks: [] }, issuers: issuer, config: cfg }, '2026-11-03T12:00:00Z'); assert.equal(plan(s, '2026-11-03T12:00:00Z').action.provider, 'searx'); });
test('unsafe Searx base URL produces configuration_required', () => { const s = init({ latest: {}, config: { ...cfg, searxBaseUrl: 'http://127.0.0.1/search' } }, '2026-11-03T12:00:00Z'); assert.equal(plan(s, '2026-11-03T12:00:00Z').state.outcome, 'configuration_required'); });

test('actual pegReview status object selects needs_review and skips other statuses', () => { const latest = { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', pegReview: { status: 'needs_review' } }, { code: 'BBB', pegReview: { status: 'available' } }, { code: 'CCC', pegReview: { status: 'not_applicable' } }] }; const s = init({ latest, issuers: { ...issuer, BBB: issuer.AAA, CCC: issuer.AAA }, config: cfg }, '2026-11-03T12:00:00Z'); assert.deepEqual(s.stocks.map(x => x.code), ['AAA']); });
test('Chinese financial titles work without URL, TextEncoder, or structuredClone globals', () => { const vm = require('node:vm'); const fs = require('node:fs'); const source = fs.readFileSync(require.resolve('./peg-source-discovery.cjs'), 'utf8'); const module = { exports: {} }; vm.runInNewContext(source, { module, exports: module.exports, URL: undefined, TextEncoder: undefined, structuredClone: undefined, Date, Number, Array, Object, String, Boolean, RegExp, Math, Map, Set, encodeURIComponent, JSON }); const api = module.exports; const s = api.init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: { status: 'needs_review' } }] }, issuers: issuer, config: cfg }, '2026-11-03T12:00:00Z'); const p = api.plan(s, '2026-11-03T12:00:00Z'); const n = api.apply(p.state, 'searx', { statusCode: 200, body: { results: [{ url: 'https://alpha.example/investor/news', title: '第三季財報' }] } }, '2026-11-03T12:00:01Z'); assert.equal(api.plan(n, '2026-11-03T12:00:02Z').state.manifest.stocks[0].results[0].provider, 'searx'); });
test('Searx base normalization targets /search and rejects embedded query strings', () => {
  const actionFor = searxBaseUrl => plan(init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, config: { ...cfg, searxBaseUrl } }, '2026-11-03T12:00:00Z'), '2026-11-03T12:00:00Z');
  assert.match(actionFor('http://searxng:8080').action.url, /^http:\/\/searxng:8080\/search\?/);
  assert.match(actionFor('http://searxng:8080/').action.url, /^http:\/\/searxng:8080\/search\?/);
  assert.match(actionFor('https://searxng.local/searx').action.url, /^https:\/\/searxng\.local\/searx\/search\?/);
  assert.match(actionFor('http://searxng:8080/searx/search/').action.url, /^http:\/\/searxng:8080\/searx\/search\?/);
  const embedded = actionFor('http://searxng:8080/search?token=must-not-leak');
  assert.equal(embedded.done, true);
  assert.equal(embedded.state.outcome, 'configuration_required');
});

test('Brave 429 cooldown skips repeat fallback calls in the same batch', () => {
  const latest = { marketDate: cfg.marketDate, stocks: ['AAA', 'BBB'].map(code => ({ code, name: code, pegReview: 'needs_review' })) };
  let state = init({ latest, issuers: { ...issuer, BBB: { officialDomains: ['beta.example'] } }, config: cfg }, '2026-11-03T12:00:00Z');
  let p = plan(state, '2026-11-03T12:00:00Z');
  state = apply(p.state, 'searx', { statusCode: 500 }, '2026-11-03T12:00:01Z');
  p = plan(state, '2026-11-03T12:00:02Z');
  assert.equal(p.action.provider, 'brave');
  state = apply(p.state, 'brave', { statusCode: 429, headers: { 'Retry-After': '60' } }, '2026-11-03T12:00:03Z');
  p = plan(state, '2026-11-03T12:00:04Z');
  assert.equal(p.done, true);
  assert.equal(p.state.manifest.stocks[1].reason, 'source_unavailable');
  assert.equal(p.state.attempts.BBB, undefined);
});
test('same-day cached Brave quota of 20 survives reuse and blocks the next fallback', () => {
  const cachedManifest = { marketDate: cfg.marketDate, generatedAt: '2026-11-03T11:00:00Z', searchUsage: { date: cfg.marketDate, brave: 20 }, stocks: [] };
  const latest = { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] };
  let state = init({ latest, issuers: issuer, cachedManifest, config: cfg }, '2026-11-03T12:00:00Z');
  assert.equal(state.braveUsed, 20);
  let p = plan(state, '2026-11-03T12:00:00Z');
  assert.equal(p.action.provider, 'searx');
  state = apply(p.state, 'searx', { statusCode: 503 }, '2026-11-03T12:00:01Z');
  p = plan(state, '2026-11-03T12:00:02Z');
  assert.equal(p.done, true);
  assert.equal(p.state.manifest.stocks[0].reason, 'budget_exhausted');
  assert.equal(p.state.manifest.searchUsage.brave, 20);
});

test('Searx accepts explicitly configured private service endpoints only', () => {
  for (const endpoint of ['http://searxng:8080/search', 'https://searxng.local/search', 'http://10.20.30.40:8080/search', 'http://172.20.0.4:8080/search', 'http://192.168.1.9:8080/search']) {
    const s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, config: { ...cfg, searxBaseUrl: endpoint } }, '2026-11-03T12:00:00Z');
    const p = plan(s, '2026-11-03T12:00:00Z');
    assert.equal(p.action.provider, 'searx', endpoint);
  }
  for (const endpoint of [
    'https://searx.example.com/search', 'http://8.8.8.8/search', 'http://169.254.169.254/latest/meta-data',
    'http://169.254.10.2/search', 'http://127.0.0.1:8080/search', 'http://searxng:0/search',
    'http://searxng:65536/search', 'http://user@searxng:8080/search', 'http://searxng:8080/search?token=x',
    'http://searxng:8080/search#fragment', 'http://searxng:8080\\evil.test', 'http://metadata.internal/search', 'http://searxng:8080\r\nX-Injected: yes/search',
  ]) {
    const s = init({ latest: { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] }, issuers: issuer, config: { ...cfg, searxBaseUrl: endpoint } }, '2026-11-03T12:00:00Z');
    const p = plan(s, '2026-11-03T12:00:00Z');
    assert.equal(p.done, true, endpoint);
    assert.equal(p.state.outcome, 'configuration_required', endpoint);
  }
});
test('private and HTTP discovery results are rejected; an unset service URL never falls through to Brave', () => {
  const latest = { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: 'needs_review' }] };
  const issuerWithPrivateDomains = { AAA: { legalName: 'Alpha Corp', officialDomains: ['searxng', '10.20.30.40', 'alpha.example'] } };
  const s = init({ latest, issuers: issuerWithPrivateDomains, config: cfg }, '2026-11-03T12:00:00Z');
  const p = plan(s, '2026-11-03T12:00:00Z');
  const n = apply(p.state, 'searx', { statusCode: 200, body: { results: [
    { url: 'http://alpha.example/report.pdf', title: 'Financial report' },
    { url: 'https://searxng/report.pdf', title: 'Financial report' },
    { url: 'https://10.20.30.40/report.pdf', title: 'Financial report' },
    { url: 'https://alpha.example/investor/report.pdf', title: 'Financial report' },
  ] } }, '2026-11-03T12:00:01Z');
  assert.deepEqual(n.stocks[0].results.map(result => result.url), ['https://alpha.example/investor/report.pdf']);
  const blank = init({ latest, issuers: issuerWithPrivateDomains, config: { ...cfg, searxBaseUrl: '' } }, '2026-11-03T12:00:00Z');
  const noFallback = plan(blank, '2026-11-03T12:00:00Z');
  assert.equal(noFallback.done, true);
  assert.equal(noFallback.state.outcome, 'configuration_required');
  assert.equal(noFallback.action, undefined);
});
test('provider config/auth errors disable that provider for the batch and keep diagnostics sanitized', () => {
  const latest = { marketDate: cfg.marketDate, stocks: ['AAA', 'BBB'].map(code => ({ code, name: code, pegReview: 'needs_review' })) };
  let state = init({ latest, issuers: { ...issuer, BBB: { officialDomains: ['beta.example'] } }, config: cfg }, '2026-11-03T12:00:00Z');
  let p = plan(state, '2026-11-03T12:00:00Z');
  state = apply(p.state, 'searx', { statusCode: 422, body: { api_key: 'searx-secret', message: 'invalid endpoint' }, headers: { authorization: 'Bearer searx-secret' } }, '2026-11-03T12:00:01Z');
  p = plan(state, '2026-11-03T12:00:02Z');
  assert.equal(p.action.provider, 'brave');
  state = apply(p.state, 'brave', { statusCode: 422, body: { api_key: 'brave-secret', message: 'wrong API key' }, headers: { authorization: 'Bearer brave-secret' } }, '2026-11-03T12:00:03Z');
  p = plan(state, '2026-11-03T12:00:04Z');
  assert.equal(p.done, true);
  assert.equal(p.state.attempts.AAA.searx, 1);
  assert.equal(p.state.attempts.AAA.brave, 1);
  assert.equal(p.state.attempts.BBB, undefined);
  assert.deepEqual(p.state.manifest.providerErrors.map(({ provider, statusCode, reason }) => ({ provider, statusCode, reason })), [
    { provider: 'searx', statusCode: 422, reason: 'provider_configuration_or_auth' },
    { provider: 'brave', statusCode: 422, reason: 'provider_configuration_or_auth' },
  ]);
  const serialized = JSON.stringify(p.state.manifest);
  for (const secret of ['searx-secret', 'brave-secret', 'api_key', 'authorization', 'invalid endpoint', 'wrong API key']) assert.equal(serialized.includes(secret), false);
});
test('429 and 5xx responses cool the affected provider down for the rest of the batch', () => {
  const latest = { marketDate: cfg.marketDate, stocks: ['AAA', 'BBB'].map(code => ({ code, name: code, pegReview: 'needs_review' })) };
  let state = init({ latest, issuers: { ...issuer, BBB: { officialDomains: ['beta.example'] } }, config: cfg }, '2026-11-03T12:00:00Z');
  let p = plan(state, '2026-11-03T12:00:00Z');
  state = apply(p.state, 'searx', { statusCode: 503, headers: { 'retry-after': '30' } }, '2026-11-03T12:00:01Z');
  p = plan(state, '2026-11-03T12:00:02Z');
  assert.equal(p.action.provider, 'brave');
  state = apply(p.state, 'brave', { statusCode: 502 }, '2026-11-03T12:00:03Z');
  p = plan(state, '2026-11-03T12:00:04Z');
  assert.equal(p.done, true);
  assert.equal(p.state.attempts.BBB, undefined);
  assert.deepEqual(p.state.manifest.providerErrors.map(e => [e.provider, e.statusCode, e.reason]), [
    ['searx', 503, 'provider_server_error'], ['brave', 502, 'provider_server_error'],
  ]);
});

test('search period uses the most recently disclosed nested quarter instead of calendar quarter', () => {
  const latest = { marketDate: cfg.marketDate, stocks: [{ code: 'AAA', name: 'Alpha', pegReview: { status: 'needs_review', currentPeriod: '2025Q3–2026Q2' } }] };
  const s = init({ latest, issuers: issuer, config: cfg }, '2026-11-03T12:00:00Z');
  const p = plan(s, '2026-11-03T12:00:00Z');
  assert.match(decodeURIComponent(p.action.url), /2026Q2/);
  assert.doesNotMatch(decodeURIComponent(p.action.url), /2026Q3/);
});
test('each provider config/auth status code disables the provider for all remaining stocks', () => {
  for (const statusCode of [400, 401, 403, 422]) {
    const latest = { marketDate: cfg.marketDate, stocks: ['AAA', 'BBB'].map(code => ({ code, name: code, pegReview: 'needs_review' })) };
    const issuers = { ...issuer, BBB: { officialDomains: ['beta.example'] } };
    let state = init({ latest, issuers, config: cfg }, '2026-11-03T12:00:00Z');
    let p = plan(state, '2026-11-03T12:00:00Z');
    state = apply(p.state, 'searx', { statusCode }, '2026-11-03T12:00:01Z');
    p = plan(state, '2026-11-03T12:00:02Z');
    assert.equal(p.action.provider, 'brave', `Searx status ${statusCode} must get one fallback`);
    state = apply(p.state, 'brave', { statusCode }, '2026-11-03T12:00:03Z');
    p = plan(state, '2026-11-03T12:00:04Z');
    assert.equal(p.done, true, `fatal status ${statusCode} must stop further requests`);
    assert.equal(p.state.attempts.BBB, undefined, `fatal status ${statusCode} must not repeat for next stock`);
    assert.equal(p.state.manifest.providerErrors.length, 2);
  }
});
