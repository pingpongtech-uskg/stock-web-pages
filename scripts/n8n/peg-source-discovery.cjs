'use strict';

const MAX_RESULTS = 5;
const COOLDOWN_MS = 300_000;
const DAY_MS = 86_400_000;
const PRIVATE_SUFFIXES = ['.localhost', '.local', '.internal', '.test'];

function parseHttps(value) {
  if (typeof value !== 'string') return null;
  const match = value.match(/^https:\/\/([^/?#]+)([^?#]*)(?:\?([^#]*))?(?:#.*)?$/i);
  if (!match || match[1].includes('@')) return null;
  const authority = match[1];
  const host = authority.replace(/:\d+$/, '').toLowerCase().replace(/\.$/, '');
  const port = authority.match(/:(\d+)$/)?.[1];
  if (port && (Number(port) < 1 || Number(port) > 65535)) return null;
  if (!/^[a-z0-9.-]+$/.test(host) || host.startsWith('.') || host.endsWith('.') || host.includes('..')) return null;
  return isPublicHostname(host) ? { host, path: match[2] || '/', query: match[3] || '', authority } : null;
}
function validHttpsUrl(value) { return Boolean(parseHttps(value)); }
function parseServiceUrl(value, allowQuery = false) {
  if (typeof value !== 'string' || /[#\\\s\u0000-\u001f\u007f]/.test(value)) return null;
  const match = value.match(/^(https?):\/\/([^/?#]+)([^?#]*)(?:\?([^#]*))?$/i);
  if (!match || match[4] && !allowQuery) return null;
  if (match[2].includes('@')) return null;
  const authority = match[2];
  const parts = authority.match(/^([a-z0-9.-]+)(?::(\d+))?$/i);
  if (!parts) return null;
  const host = parts[1].toLowerCase().replace(/\.$/, '');
  const port = parts[2] === undefined ? null : Number(parts[2]);
  if (parts[2] !== undefined && (!Number.isInteger(port) || port < 1 || port > 65535)) return null;
  if (!host || host.length > 253 || host.startsWith('.') || host.endsWith('.') || host.includes('..')) return null;
  const labels = host.split('.');
  if (labels.some(label => !label || label.length > 63 || !/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label))) return null;
  const ip = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (ip) {
    const octets = ip.slice(1).map(Number);
    if (octets.some(n => n > 255)) return null;
    const privateIpv4 = octets[0] === 10 || octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31 || octets[0] === 192 && octets[1] === 168;
    if (!privateIpv4) return null;
  } else {
    const internalSuffixes = ['.local', '.internal', '.svc', '.cluster.local', '.docker', '.test', '.private', '.home.arpa'];
    const singleLabelService = labels.length === 1 && !['localhost', 'metadata', 'instance-data'].includes(host);
    if (!singleLabelService && !internalSuffixes.some(suffix => host.endsWith(suffix))) return null;
    if (host === 'localhost' || host.endsWith('.localhost') || host.split('.')[0] === 'metadata' || host.split('.')[0] === 'instance-data') return null;
  }
  return { scheme: match[1].toLowerCase(), authority: `${host}${port === null ? '' : `:${port}`}`, host, path: match[3] || '/', query: match[4] || '' };
}
function validServiceUrl(value, allowQuery = false) { return Boolean(parseServiceUrl(value, allowQuery)); }
function isPublicHostname(host) {
  const h = host.toLowerCase().replace(/^\[|\]$/g, '');
  if (!h.includes('.') || PRIVATE_SUFFIXES.some(s => h.endsWith(s))) return false;
  if (/^(localhost|\d{1,3}(\.\d{1,3}){3}|\d+)$/.test(h) || h.includes(':')) return false;
  const octets = h.split('.').map(Number);
  if (octets.length === 4 && octets.every(n => n >= 0 && n <= 255)) {
    return !(octets[0] === 10 || octets[0] === 127 || octets[0] === 0 || octets[0] === 169 && octets[1] === 254 || octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31 || octets[0] === 192 && octets[1] === 168);
  }
  return true;
}
function hostOf(value) { return parseHttps(value)?.host.replace(/^www\./, '') || ''; }
function approved(url, domains) {
  const host = hostOf(url);
  return Boolean(host && domains.some(d => { const root = String(d).toLowerCase().replace(/^https?:\/\//, '').split('/')[0].replace(/^www\./, '').replace(/\.$/, ''); return root && (host === root || host.endsWith(`.${root}`)); }));
}
function financial(item) {
  const text = `${item.title || ''} ${item.url || ''}`.toLowerCase();
  return /(investor|financial|earnings|quarter|annual|results|report|filing|\b10[- ]?[qk]\b|eps|\.pdf(?:$|\?)|財務|財報|每股盈餘|季報|年報|法人說明會|法說|投資人)/i.test(text);
}
function shapeResults(items, provider, domains) {
  if (!Array.isArray(items)) return [];
  const seen = new Set(), out = [];
  for (const item of items) {
    if (!item || typeof item.url !== 'string' || !validHttpsUrl(item.url) || !approved(item.url, domains) || !financial(item)) continue;
    const parsed = parseHttps(item.url);
    const url = `https://${parsed.authority.toLowerCase()}${parsed.path}${parsed.query ? `?${parsed.query}` : ''}`;
    if (seen.has(url)) continue;
    seen.add(url); out.push({ url, title: String(item.title || '').slice(0, 300), provider });
    if (out.length >= MAX_RESULTS) break;
  }
  return out;
}
function getItems(provider, body) {
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch { return []; } }
  return provider === 'searx' ? body?.results : body?.web?.results;
}
function retryMs(headers, now) {
  const value = headers && (headers['retry-after'] || headers['Retry-After']);
  let ms = Number(value) * 1000;
  if (!Number.isFinite(ms) || ms < 0) ms = value ? Math.max(0, Date.parse(value) - Date.parse(now)) : 0;
  return Math.max(COOLDOWN_MS, Math.min(ms || 0, 86_400_000));
}
function queryFor(stock) {
  const d = stock.domains[0] || '';
  const match = String(stock.period || '').match(/^(\d{4})\s*-?\s*Q([1-4])$/i);
  if (!match) return `site:${d} (EPS OR 每股盈餘 OR earnings)`;
  const year = Number(match[1]);
  const quarter = Number(match[2]);
  const rocYear = year - 1911;
  const quarterName = ['', '一', '二', '三', '四'][quarter];
  const quarterAliases = [`Q${quarter}`, `${quarter}Q${String(year).slice(-2)}`, `第${quarterName}季`, `第${quarter}季`];
  return `site:${d} (${year} OR ${rocYear}) (${quarterAliases.join(' OR ')}) (EPS OR 每股盈餘 OR earnings)`;
}
function searxUrl(base, query) {
  if (typeof base !== 'string' || /[?#]/.test(base)) return '';
  const parsed = parseServiceUrl(base);
  if (!parsed) return '';
  let path = parsed.path.replace(/\/+$/, '');
  if (!path) path = '/search';
  else if (!/\/search$/i.test(path)) path += '/search';
  return `${parsed.scheme}://${parsed.authority}${path}?q=${encodeURIComponent(query)}&format=json`;
}
function disclosedQuarter(stock) {
  for (const value of [stock?.currentPeriod, stock?.pegReview?.currentPeriod]) {
    if (typeof value !== 'string') continue;
    const matches = [...value.matchAll(/(\d{4})\s*Q\s*([1-4])/gi)];
    if (matches.length) { const latest = matches[matches.length - 1]; return `${latest[1]}Q${latest[2]}`; }
  }
  return null;
}
function previousQuarter(marketDate) {
  const m = String(marketDate).match(/^(\d{4})-(\d{2})/);
  if (!m) return 'latest completed quarter';
  let year = Number(m[1]), quarter = Math.ceil(Number(m[2]) / 3) - 1;
  if (quarter < 1) { year--; quarter = 4; }
  return `${year}Q${quarter}`;
}
function safeConfig(config) {
  return Boolean(config && typeof config.marketDate === 'string' && config.marketDate && typeof config.requestId === 'string' && config.requestId && Number.isInteger(config.braveDailyLimit) && config.braveDailyLimit >= 0 && validServiceUrl(config.searxBaseUrl));
}
function init(input = {}, now = new Date().toISOString()) {
  const { latest, issuers = {}, cachedManifest, config = {} } = input;
  const state = { config: { ...config }, cursor: 0, stocks: [], pending: null, unavailable: {}, attempts: {}, providerErrors: sanitizeProviderErrors(cachedManifest?.providerErrors), outcome: null, manifest: null };
  const oldUsage = cachedManifest?.searchUsage || {};
  state.braveUsed = oldUsage.date === config.marketDate ? Number(oldUsage.brave) || 0 : 0;
  if (!safeConfig(config)) { state.outcome = 'configuration_required'; state.manifest = { marketDate: config.marketDate || null, requestId: config.requestId || null, generatedAt: now, searchUsage: { date: config.marketDate || null, brave: state.braveUsed }, stocks: [] }; return state; }
  const cacheTime = Date.parse(cachedManifest?.generatedAt);
  const reusable = cachedManifest?.marketDate === config.marketDate && (!config.candidateSha256 || cachedManifest?.candidateSha256 === config.candidateSha256) && Number.isFinite(cacheTime) && Date.parse(now) - cacheTime >= 0 && Date.parse(now) - cacheTime < DAY_MS;
  const latestStocks = Array.isArray(latest?.stocks) ? latest.stocks : [];
  let candidates = latestStocks.filter(x => x?.pegDiscoveryRequired === true || (typeof x?.pegReview === 'string' ? x.pegReview : x?.pegReview?.status) === 'needs_review');
  if (!candidates.length && latest?.marketDate === config.marketDate && !latestStocks.some(x => x?.pegReview && (typeof x.pegReview !== 'object' || x.pegReview.status))) candidates = config.bootstrapCandidates || [];
  state.stocks = candidates.map(x => {
    const code = String(x.code || '').trim();
    const record = issuers[code] || issuers[code.toUpperCase()] || {};
    const expected = x?.pegReview?.expectedLatestQuarter || x?.expectedLatestQuarter;
    const expectedLatestQuarter = /^\d{4}Q[1-4]$/.test(expected || '') ? expected : null;
    return { code, name: String(x.name || record.name || code), expectedLatestQuarter, period: expectedLatestQuarter || disclosedQuarter(x) || previousQuarter(config.marketDate), legalName: String(record.legalName || record.name || x.name || code), domains: Array.isArray(record.officialDomains) ? record.officialDomains.filter(d => typeof d === 'string' && d) : [], results: null, reason: null, nextProvider: 'searx' };
  });
  if (reusable) {
    const cached = new Map((cachedManifest.stocks || []).map(x => [x.code, x]));
    state.stocks = state.stocks.map(s => cached.has(s.code) ? { ...s, results: cached.get(s.code).results || [], reason: cached.get(s.code).reason, nextProvider: null } : s);
  }
  return state;
}
function cleanProviderErrors(value) {
  if (!Array.isArray(value)) return [];
  const reasons = new Set(['provider_configuration_or_auth', 'provider_client_error', 'provider_rate_limited', 'provider_server_error', 'provider_request_failed', 'provider_unavailable']);
  return value.filter(e => e && ['searx', 'brave'].includes(e.provider) && Number.isInteger(e.statusCode) && e.statusCode >= 0 && e.statusCode <= 599 && reasons.has(e.reason) && typeof e.time === 'string' && Number.isFinite(Date.parse(e.time)))
    .map(e => ({ provider: e.provider, statusCode: e.statusCode, reason: e.reason, time: new Date(e.time).toISOString() }));
}
function sanitizeProviderErrors(value) { return cleanProviderErrors(value); }
function addProviderError(state, provider, statusCode, response, now) {
  let reason;
  if ([400, 401, 403, 422].includes(statusCode)) reason = 'provider_configuration_or_auth';
  else if (statusCode === 429) reason = 'provider_rate_limited';
  else if (statusCode >= 500) reason = 'provider_server_error';
  else if (response.error && statusCode === 0) reason = 'provider_unavailable';
  else reason = 'provider_client_error';
  state.providerErrors.push({ provider, statusCode, reason, time: new Date(now).toISOString() });
}
function cloneState(state) { return JSON.parse(JSON.stringify(state)); }
function finalize(state, now) {
  const stocks = state.stocks.map(s => ({ code: s.code, name: s.name, legalName: s.legalName, officialDomains: [...s.domains], results: s.results || [], providerAttempts: { ...(state.attempts[s.code] || {}) }, ...(s.reason ? { reason: s.reason } : {}) }));
  state.manifest = { marketDate: state.config.marketDate, requestId: state.config.requestId, generatedAt: now, searchUsage: { date: state.config.marketDate, brave: state.braveUsed }, providerErrors: sanitizeProviderErrors(state.providerErrors), stocks };
  return { state, done: true };
}
function plan(inputState, now = new Date().toISOString()) {
  const state = cloneState(inputState);
  if (state.outcome === 'configuration_required') return { state, done: true, outcome: state.outcome };
  if (state.pending) return { state, done: false, action: { ...state.pending } };
  while (state.cursor < state.stocks.length) {
    const s = state.stocks[state.cursor];
    if (s.results !== null) { state.cursor++; continue; }
    if (!s.domains.length) { s.results = []; s.reason = 'source_not_found'; state.cursor++; continue; }
    let provider = s.nextProvider || 'searx';
    if (provider === 'searx' && state.unavailable.searx > Date.parse(now)) provider = 'brave';
    if (provider === 'brave') {
      if (state.unavailable.brave > Date.parse(now)) { s.results = []; s.reason = 'source_unavailable'; state.cursor++; continue; }
      if (state.braveUsed >= state.config.braveDailyLimit) { s.results = []; s.reason = 'budget_exhausted'; state.cursor++; continue; }
    }
    const query = queryFor(s);
    const url = provider === 'searx' ? searxUrl(state.config.searxBaseUrl, query) : `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=5`;
    if (!(provider === 'searx' ? validServiceUrl(url, true) : validHttpsUrl(url))) { state.outcome = 'configuration_required'; return { state, done: true, outcome: state.outcome }; }
    const action = { provider, url, method: 'GET' };
    state.pending = action;
    state.attempts[s.code] = { ...(state.attempts[s.code] || {}), [provider]: ((state.attempts[s.code] || {})[provider] || 0) + 1 };
    if (provider === 'brave') state.braveUsed++;
    return { state, done: false, action: { ...action } };
  }
  return finalize(state, now);
}
function apply(inputState, provider, response = {}, now = new Date().toISOString()) {
  const state = cloneState(inputState);
  const action = state.pending;
  if (!action || action.provider !== provider) return state;
  state.pending = null;
  const stock = state.stocks[state.cursor];
  const status = Number(response.statusCode) || 0;
  const valid = status >= 200 && status < 300 && !response.error;
  if (!valid) {
    addProviderError(state, provider, status, response, now);
    if ([400, 401, 403, 422].includes(status) || status >= 400 && status < 500 && status !== 429) state.unavailable[provider] = Number.MAX_SAFE_INTEGER;
    else if (status === 429 || status >= 500 || response.error && status === 0) state.unavailable[provider] = Date.parse(now) + retryMs(response.headers, now);
  }
  const results = valid ? shapeResults(getItems(provider, response.body), provider, stock.domains) : [];
  if (results.length) { stock.results = results; stock.reason = null; state.cursor++; return state; }
  if (provider === 'searx') { stock.nextProvider = 'brave'; return state; }
  stock.results = [];
  stock.reason = state.unavailable.brave > Date.parse(now) ? 'source_unavailable' : 'source_not_found';
  state.cursor++;
  return state;
}
module.exports = { init, plan, apply };
