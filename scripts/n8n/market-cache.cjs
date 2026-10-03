'use strict';

// Pure byte/coverage contract. Callers must obtain `expected` independently from
// authenticated Actions lineage and the official universe; never from this manifest.
// Upload/network/lease handling belongs to the existing deterministic writer.
const { createHash } = require('crypto');
const MAX_GZIP = 4 * 1024 * 1024;
const MAX_RAW = 32 * 1024 * 1024;
const MAX_TOTAL_RAW = 256 * 1024 * 1024;
const MAX_TOTAL_GZIP = 64 * 1024 * 1024;
const MAX_PARTS = 256;
const ROLES = Object.freeze([
  'institutional_raw:TWSE', 'institutional_raw:TPEx',
  'institutional_normalized:TWSE', 'institutional_normalized:TPEx',
  'calendar_raw', 'calendar_normalized', 'volume_raw', 'volume_normalized', 'published_stock_inputs',
]);
const HASH = /^[a-f0-9]{64}$/;
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const check = (ok, reason) => { if (!ok) throw new Error(`cache_${reason}`); };
const equal = (a, b) => a === undefined || b === undefined ? a === b : canonical(a) === canonical(b);
const unique = values => new Set(values).size === values.length;
const integer = value => Number.isSafeInteger(value) && value >= 0;

function canonical(value, depth = 0) {
  check(depth <= 24, 'json_depth');
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') { check(Number.isFinite(value), 'numbers'); return JSON.stringify(value); }
  if (Array.isArray(value)) return `[${value.map(item => canonical(item, depth + 1)).join(',')}]`;
  check(value && Object.getPrototypeOf(value) === Object.prototype, 'json');
  const keys = Object.keys(value).sort();
  check(!keys.some(key => /^(token|api_?key|password|authorization|accountIdentity|accountEmail|rawLogs|signedUrl)$/i.test(key)), 'secret');
  return `{${keys.map(key => `${JSON.stringify(key)}:${canonical(value[key], depth + 1)}`).join(',')}}`;
}

function validDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
function validUtc(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));
}
function validateHeader(value) {
  check(value && validDate(value.marketDate) && validDate(value.previousTradingDate) && value.previousTradingDate < value.marketDate, 'dates');
  check(validUtc(value.generatedAt), 'generated_at');
  const source = value.source;
  check(source && /^[a-f0-9]{40}$/.test(source.sourceGitCommit) && /^\d{1,20}$/.test(source.actionsRunId) && /^[a-zA-Z0-9:_-]{1,160}$/.test(source.requestId), 'lineage');
  check(equal(Object.keys(source).sort(), ['actionsRunId', 'requestId', 'sourceGitCommit']), 'lineage');
}
function validateRoles(groups) {
  check(Array.isArray(groups) && equal(groups.map(group => group.key).sort(), [...ROLES].sort()), 'roles');
}
function safeSourceUrl(url) {
  if (typeof url !== 'string' || !/^https:\/\/[a-zA-Z0-9.-]+\/[^\s#]*$/.test(url)) return false;
  try {
    return (url.split('?')[1] || '').split('&').every(field => {
      const key = decodeURIComponent(field.split('=')[0]).replace(/[-_]/g, '').toLowerCase();
      return !/(token|secret|password|apikey|authorization|signature|credential)/.test(key) && !['sig', 'key', 'auth'].includes(key) && !key.startsWith('xamz');
    });
  } catch { return false; }
}
function validateGroup(group, marketDate, previousTradingDate) {
  check(group && ROLES.includes(group.key), 'roles');
  const [kind, market] = group.key.split(':');
  check(group.kind === kind && group.market === (market || (kind === 'published_stock_inputs' ? 'ALL' : 'TWSE')), 'roles');
  check(Array.isArray(group.dates) && group.dates.length > 0 && group.dates.length <= 60 && unique(group.dates) && group.dates.every(validDate) && equal(group.dates, [...group.dates].sort()), 'dates');
  check(group.dates.at(-1) === marketDate, 'dates');
  if (kind.startsWith('volume')) check(group.dates.includes(previousTradingDate), 'dates');
  check(Array.isArray(group.codes) && group.codes.length <= 10000 && unique(group.codes) && group.codes.every(code => typeof code === 'string' && /^\d{4,6}[A-Z]?$/.test(code)) && equal(group.codes, [...group.codes].sort()), 'codes');
  check(kind.startsWith('calendar') ? group.codes.length === 0 : group.codes.length > 0, 'codes');
  if (kind.startsWith('institutional')) {
    const membership = group.codesByDate;
    check(membership && Object.getPrototypeOf(membership) === Object.prototype && equal(Object.keys(membership).sort(), group.dates), 'membership');
    const perDate = group.dates.map(date => membership[date]);
    check(perDate.every(codes => Array.isArray(codes) && codes.length > 0 && unique(codes) && codes.every(code => group.codes.includes(code)) && equal(codes, [...codes].sort())), 'membership');
    check(equal([...new Set(perDate.flat())].sort(), group.codes), 'membership');
  }
  if (kind.startsWith('volume')) check(equal(group.codes, ['00631L']), 'codes');
  check(['shares', 'lots', 'mixed', 'calendar'].includes(group.unit), 'units');
  if (kind === 'institutional_normalized' || kind === 'volume_normalized') check(group.unit === 'shares', 'units');
  if (kind.startsWith('calendar')) check(group.unit === 'calendar', 'units');
  if (kind === 'published_stock_inputs') check(group.unit === 'mixed', 'units');
  check(safeSourceUrl(group.sourceUrl), 'source_url');
  check(HASH.test(group.sourceSha256) && (group.normalizedFromSha256 === null || HASH.test(group.normalizedFromSha256)), 'source_hash');
  check(kind.endsWith('_normalized') ? group.normalizedFromSha256 === group.sourceSha256 : group.normalizedFromSha256 === null, 'source_hash');
}

function encodeShards(bytes, key, limits) {
  if (bytes.length > limits.maxRawBytes) {
    const midpoint = Math.floor(bytes.length / 2);
    return [...encodeShards(bytes.subarray(0, midpoint), key, limits), ...encodeShards(bytes.subarray(midpoint), key, limits)];
  }
  const gzip = require('zlib').gzipSync(bytes, { level: 9, mtime: 0 });
  if (gzip.length > limits.maxCompressedBytes) {
    check(bytes.length > 1, 'limit');
    const midpoint = Math.floor(bytes.length / 2);
    return [...encodeShards(bytes.subarray(0, midpoint), key, limits), ...encodeShards(bytes.subarray(midpoint), key, limits)];
  }
  return [{ bytes: gzip, rawBytes: bytes.length, rawSha256: sha(bytes), gzipBytes: gzip.length, gzipSha256: sha(gzip) }];
}
function buildGroup(group, header, limits) {
  validateGroup(group, header.marketDate, header.previousTradingDate);
  const { body, ...metadata } = group;
  const raw = Buffer.isBuffer(body) ? Buffer.from(body) : Buffer.from(canonical(body), 'utf8');
  check(raw.length > 0 && raw.length <= MAX_TOTAL_RAW, 'raw_size');
  if (group.kind.endsWith('_raw')) check(sha(raw) === group.sourceSha256, 'source_hash');
  const encoded = encodeShards(raw, group.key, limits);
  check(encoded.length <= MAX_PARTS, 'part_count');
  const parts = encoded.map((part, index) => ({ name: `${header.marketDate}.${group.key.replace(':', '-')}.${index}.${part.gzipSha256}.json.gz`, index, ...part }));
  return { descriptor: { ...metadata, representation: Buffer.isBuffer(body) ? 'bytes' : 'json', codesHash: sha(canonical(group.codes)), rawBytes: raw.length, rawSha256: sha(raw), shards: parts.map(({ bytes, ...part }) => part) }, files: Object.fromEntries(parts.map(part => [part.name, part.bytes])) };
}
function manifestDigest(manifest) { const { manifestHash, ...body } = manifest; return sha(canonical(body)); }

function buildMarketCache(input, options = {}) {
  validateHeader(input); validateRoles(input.groups);
  const limits = { maxCompressedBytes: MAX_GZIP, maxRawBytes: MAX_RAW, ...options };
  check(integer(limits.maxCompressedBytes) && limits.maxCompressedBytes >= 32 && limits.maxCompressedBytes <= MAX_GZIP && integer(limits.maxRawBytes) && limits.maxRawBytes >= 1 && limits.maxRawBytes <= MAX_RAW, 'limit');
  const built = input.groups.map(group => buildGroup(group, input, limits));
  const { groups, ...header } = input;
  const manifest = { ...header, schemaVersion: 'market-cache-v1', groups: built.map(group => group.descriptor) };
  const files = Object.assign({}, ...built.map(group => group.files));
  check(Object.keys(files).length <= MAX_PARTS && Object.values(files).reduce((sum, bytes) => sum + bytes.length, 0) <= MAX_TOTAL_GZIP && manifest.groups.reduce((sum, group) => sum + group.rawBytes, 0) <= MAX_TOTAL_RAW, 'total_limit');
  return { manifest: { ...manifest, manifestHash: manifestDigest(manifest) }, files };
}

function decodeCacheGroup(group, files) {
  check(Array.isArray(group.shards) && group.shards.length > 0 && group.shards.length <= MAX_PARTS, 'parts');
  for (const part of group.shards) check(typeof part.name === 'string' && /^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[a-zA-Z0-9_-]+\.[0-9]+\.[a-f0-9]{64}\.json\.gz$/.test(part.name), 'filename');
  const declaredRaw = group.shards.reduce((sum, part) => sum + part.rawBytes, 0);
  check(integer(group.rawBytes) && group.rawBytes > 0 && group.rawBytes <= MAX_TOTAL_RAW && declaredRaw === group.rawBytes, 'raw_size');
  const chunks = group.shards.map((part, index) => {
    check(part.index === index && integer(part.rawBytes) && part.rawBytes > 0 && part.rawBytes <= MAX_RAW, 'parts');
    const gzip = files[part.name];
    check(Buffer.isBuffer(gzip) && gzip.length === part.gzipBytes && gzip.length <= MAX_GZIP, 'gzip_size');
    check(HASH.test(part.gzipSha256) && sha(gzip) === part.gzipSha256, 'gzip_hash');
    let bytes;
    try { bytes = require('zlib').gunzipSync(gzip, { maxOutputLength: MAX_RAW }); } catch { throw new Error('cache_inflate_limit'); }
    check(bytes.length === part.rawBytes && HASH.test(part.rawSha256) && sha(bytes) === part.rawSha256, 'raw_hash');
    return bytes;
  });
  check(chunks.reduce((sum, part) => sum + part.length, 0) <= MAX_TOTAL_RAW, 'total_limit');
  const raw = Buffer.concat(chunks);
  check(raw.length === group.rawBytes && sha(raw) === group.rawSha256, 'raw_hash');
  return raw;
}
function rowCoverage(group, rows) {
  const institutional = group.kind === 'institutional_normalized';
  const count = institutional ? group.dates.reduce((sum, date) => sum + group.codesByDate[date].length, 0) : group.dates.length * group.codes.length;
  check(Array.isArray(rows) && rows.length === count, 'coverage');
  const keys = rows.map(row => {
    check(row && group.codes.includes(row.code) && group.dates.includes(row.marketDate), 'coverage');
    if (institutional) check(group.codesByDate[row.marketDate].includes(row.code), 'coverage');
    return `${row.marketDate}:${row.code}`;
  });
  check(unique(keys), 'coverage');
}
function validateCalendar(body, expected) {
  check(body && body.year === expected.calendarYear && body.timezone === 'Asia/Taipei', 'calendar');
  for (const field of ['closedDates', 'openExceptions']) check(Array.isArray(body[field]) && unique(body[field]) && body[field].every(value => validDate(value) && Number(value.slice(0, 4)) === body.year), 'calendar');
  check(!body.closedDates.some(date => body.openExceptions.includes(date)), 'calendar');
  const dates = expected.groups.filter(group => group.kind !== 'calendar_raw' && group.kind !== 'calendar_normalized').flatMap(group => group.dates);
  check(dates.every(date => !body.closedDates.includes(date) && (body.openExceptions.includes(date) || ![0, 6].includes(new Date(`${date}T00:00:00Z`).getUTCDay()))), 'calendar');
}
function validateRows(group, body, expected) {
  rowCoverage(group, body.rows);
  if (group.kind === 'institutional_normalized') {
    for (const row of body.rows) {
      check(row.unit === 'shares', 'units');
      check(integer(row.buy) && integer(row.sell) && Number.isSafeInteger(row.net) && row.net === row.buy - row.sell, 'numbers');
    }
  } else if (group.kind === 'volume_normalized') {
    for (const row of body.rows) { check(row.unit === 'shares', 'units'); check(integer(row.volume), 'numbers'); }
  } else {
    check(Array.isArray(expected.metricKeys) && expected.metricKeys.length > 0 && unique(expected.metricKeys), 'metrics');
    for (const row of body.rows) {
      check(row.metrics && equal(Object.keys(row.metrics).sort(), [...expected.metricKeys].sort()), 'metrics');
      check(Object.values(row.metrics).every(value => value === null || (typeof value === 'number' && Number.isFinite(value))), 'metrics');
    }
  }
}
function bindExpected(manifest, expected) {
  check(expected && manifest.marketDate === expected.marketDate && manifest.previousTradingDate === expected.previousTradingDate, 'expected_dates');
  check(HASH.test(expected.manifestHash) && expected.manifestHash === manifest.manifestHash, 'expected_manifest');
  check(equal(manifest.source, expected.source), 'expected_lineage');
  validateRoles(expected.groups);
  for (const group of manifest.groups) {
    validateGroup(group, manifest.marketDate, manifest.previousTradingDate);
    const trusted = expected.groups.find(item => item.key === group.key);
    check(['key', 'kind', 'market', 'unit', 'sourceUrl', 'sourceSha256', 'normalizedFromSha256', 'codes', 'codesByDate', 'dates'].every(field => equal(group[field], trusted[field])), 'expected_group');
    check(group.codesHash === sha(canonical(trusted.codes)), 'codes_hash');
    if (group.kind.endsWith('_normalized')) {
      const raw = manifest.groups.find(item => item.key === group.key.replace('_normalized', '_raw'));
      check(raw && raw.rawSha256 === group.normalizedFromSha256, 'source_hash');
    }
  }
}
function verifyEnvelope(manifest, files, expected) {
  validateHeader(manifest); validateRoles(manifest.groups);
  check(manifest.schemaVersion === 'market-cache-v1' && HASH.test(manifest.manifestHash) && manifestDigest(manifest) === manifest.manifestHash, 'manifest_hash');
  bindExpected(manifest, expected);
  const names = manifest.groups.flatMap(group => group.shards.map(part => part.name));
  check(names.length <= MAX_PARTS && unique(names) && equal([...names].sort(), Object.keys(files).sort()), 'files');
  check(manifest.groups.reduce((sum, group) => sum + group.rawBytes, 0) <= MAX_TOTAL_RAW && Object.values(files).reduce((sum, bytes) => sum + bytes.length, 0) <= MAX_TOTAL_GZIP, 'total_limit');
  return names;
}
function verifyMarketCache(manifest, files, expected) {
  const names = verifyEnvelope(manifest, files, expected);
  const decoded = manifest.groups.map(group => {
    const raw = decodeCacheGroup(group, files);
    if (group.kind.endsWith('_raw')) check(sha(raw) === group.sourceSha256, 'source_hash');
    if (group.kind.endsWith('_raw')) return null;
    check(group.representation === 'json', 'representation');
    let body; try { body = JSON.parse(raw.toString('utf8')); } catch { throw new Error('cache_json'); }
    canonical(body);
    if (group.kind === 'calendar_normalized') validateCalendar(body, expected); else validateRows(group, body, expected);
    return body;
  });
  const stocks = decoded[manifest.groups.findIndex(group => group.kind === 'published_stock_inputs')].rows;
  const metricCoverage = Object.fromEntries(expected.metricKeys.map(key => [key, { known: stocks.filter(row => row.metrics[key] !== null).length, missing: stocks.filter(row => row.metrics[key] === null).length, zero: stocks.filter(row => row.metrics[key] === 0).length }]));
  return { cacheComplete: true, manifestHash: manifest.manifestHash, groupsVerified: manifest.groups.length, verifiedParts: names, metricsComplete: Object.values(metricCoverage).every(metric => metric.missing === 0), metricCoverage };
}

function verifyProducerProof(manifest, expected, bytes, names) {
  // This custody context MUST be constructed by authenticated exact-run GitHub
  // run/artifact reads. It cannot come from manual input, Notion or the manifest.
  const lineage = expected.artifactLineage;
  check(lineage && lineage.repository === 'pingpongtech-uskg/stock-web-pages' && /^\d{1,20}$/.test(lineage.workflowId) && /^\d{1,20}$/.test(lineage.artifactId) && HASH.test(lineage.artifactSha256) && ['requestId', 'actionsRunId', 'sourceGitCommit'].every(key => lineage[key] === manifest.source[key]) && HASH.test(expected.producerProofSha256), 'producer_auth');
  check(Buffer.isBuffer(bytes) && bytes.length > 0 && bytes.length <= 1048576 && sha(bytes) === expected.producerProofSha256, 'producer_hash');
  let proof; try { proof = JSON.parse(bytes.toString('utf8')); } catch { throw new Error('cache_producer_json'); }
  canonical(proof);
  check(proof.schemaVersion === 'market-cache-producer-proof-v1' && proof.semanticValidation === 'bounded-python-v1' && proof.cacheComplete === true, 'producer_semantics');
  check(proof.marketDate === manifest.marketDate && proof.previousTradingDate === manifest.previousTradingDate && equal(proof.source, manifest.source) && proof.manifestHash === manifest.manifestHash && proof.groupsVerified === ROLES.length && equal(proof.verifiedParts, names), 'producer_binding');
  check(Array.isArray(expected.metricKeys) && expected.metricKeys.length > 0 && unique(expected.metricKeys) && proof.metricCoverage && equal(Object.keys(proof.metricCoverage).sort(), [...expected.metricKeys].sort()), 'producer_metrics');
  const stocks = manifest.groups.find(group => group.kind === 'published_stock_inputs');
  const count = stocks.codes.length * stocks.dates.length;
  const metrics = Object.values(proof.metricCoverage);
  check(metrics.every(value => value && equal(Object.keys(value).sort(), ['known', 'missing', 'zero']) && integer(value.known) && integer(value.missing) && integer(value.zero) && value.known + value.missing === count && value.zero <= value.known), 'producer_metrics');
  check(typeof proof.metricsComplete === 'boolean' && proof.metricsComplete === metrics.every(value => value.missing === 0), 'producer_metrics');
  return proof;
}
function verifyCompressedGroup(group, files) {
  check(Array.isArray(group.shards) && group.shards.length > 0 && group.shards.length <= MAX_PARTS && integer(group.rawBytes) && group.rawBytes > 0 && group.rawBytes <= MAX_TOTAL_RAW && group.shards.reduce((sum, part) => sum + part.rawBytes, 0) === group.rawBytes, 'raw_size');
  group.shards.forEach((part, index) => {
    check(part.index === index && integer(part.rawBytes) && part.rawBytes > 0 && part.rawBytes <= MAX_RAW && HASH.test(part.rawSha256), 'gzip_descriptor');
    check(typeof part.name === 'string' && /^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[a-zA-Z0-9_-]+\.[0-9]+\.[a-f0-9]{64}\.json\.gz$/.test(part.name), 'filename');
    const gzip = files[part.name];
    check(Buffer.isBuffer(gzip) && integer(part.gzipBytes) && gzip.length === part.gzipBytes && gzip.length >= 18 && gzip.length <= MAX_GZIP, 'gzip_size');
    check(HASH.test(part.gzipSha256) && sha(gzip) === part.gzipSha256, 'gzip_hash');
    // Deterministic single-member producer gzip has no optional header fields.
    // ISIZE is only a declaration; bounded Python already verified full output.
    check(gzip[0] === 0x1f && gzip[1] === 0x8b && gzip[2] === 8 && gzip[3] === 0, 'gzip_header');
    check(gzip.readUInt32LE(gzip.length - 4) === part.rawBytes, 'gzip_isize');
  });
}
function verifyCompressedMarketCache(manifest, files, expected, producerProofBytes) {
  const names = verifyEnvelope(manifest, files, expected);
  const proof = verifyProducerProof(manifest, expected, producerProofBytes, names);
  manifest.groups.forEach(group => verifyCompressedGroup(group, files));
  return { cacheComplete: proof.cacheComplete, verificationLevel: 'compressed_backup_verified', rawSemanticsVerifiedByProducer: true, independentRawSemanticsVerified: false, manifestHash: manifest.manifestHash, groupsVerified: manifest.groups.length, verifiedParts: names, metricsComplete: proof.metricsComplete, metricCoverage: JSON.parse(canonical(proof.metricCoverage)), producerProofSha256: expected.producerProofSha256, artifactId: expected.artifactLineage.artifactId, artifactSha256: expected.artifactLineage.artifactSha256 };
}

function planCacheAttachments(existing, uploads, manifest) {
  const candidates = [...existing, ...uploads];
  check(candidates.every(file => file && typeof file.name === 'string' && file.name.length <= 180 && typeof file.uploadId === 'string' && /^[a-zA-Z0-9-]{1,80}$/.test(file.uploadId)), 'uploads');
  const names = manifest.groups.flatMap(group => group.shards.map(part => part.name));
  check(names.every(name => candidates.some(file => file.name === name)), 'uploads_missing');
  const files = candidates.filter((file, index) => candidates.findIndex(other => other.name === file.name) === index).map(file => ({ name: file.name, uploadId: file.uploadId }));
  return { files, manifestHash: manifest.manifestHash, activePromotionAllowed: false };
}
function promoteCacheRevision(current, manifest, proof) {
  const names = manifest.groups.flatMap(group => group.shards.map(part => part.name));
  if (!proof || proof.cacheComplete !== true || proof.manifestHash !== manifest.manifestHash || proof.groupsVerified !== ROLES.length || !equal(proof.verifiedParts, names)) return { ...current, revisionHashes: [...current.revisionHashes] };
  check(manifestDigest(manifest) === manifest.manifestHash, 'manifest_hash');
  return { ...current, activeManifestHash: manifest.manifestHash, revisionHashes: [...new Set([...current.revisionHashes, manifest.manifestHash])] };
}
function validateCacheDownload(file, policy, now = new Date().toISOString()) {
  check(policy && equal(Object.keys(policy).sort(), ['authentication', 'followRedirects', 'responseFormat']) && policy.authentication === 'none' && policy.followRedirects === false && policy.responseFormat === 'file', 'download_policy');
  // Exact documented origin plus the virtual-host origin observed from an
  // authenticated Notion file readback in execution885. Never allow wildcard S3.
  check(file && typeof file.url === 'string' && file.url.length <= 16384 && /^https:\/\/(?:s3\.us-west-2\.amazonaws\.com\/secure\.notion-static\.com|prod-files-secure\.s3\.us-west-2\.amazonaws\.com)\/[a-zA-Z0-9_./%-]+\?[^\s#]+$/.test(file.url) && !/(?:\/\.\.?\/|%2e|%2f|%5c)/i.test(file.url), 'storage');
  check(validUtc(file.expiry_time) && Number.isFinite(Date.parse(now)) && Date.parse(file.expiry_time) > Date.parse(now), 'url_expired');
  check(signedExpiryValid(file.url, file.expiry_time, Date.parse(now)), 'url_expired');
  return true;
}

function signedExpiryValid(url, expiry, now) {
  let entries;
  try { entries = url.split('?')[1].split('&').map(part => part.split('=').map(decodeURIComponent)); } catch { return false; }
  if (entries.some(parts => parts.length !== 2) || !unique(entries.map(parts => parts[0]))) return false;
  const query = Object.fromEntries(entries);
  const stamp = query['X-Amz-Date'];
  if (!/^\d{8}T\d{6}Z$/.test(stamp || '') || !/^[1-9]\d{0,3}$/.test(query['X-Amz-Expires'] || '')) return false;
  const iso = `${stamp.slice(0, 4)}-${stamp.slice(4, 6)}-${stamp.slice(6, 8)}T${stamp.slice(9, 11)}:${stamp.slice(11, 13)}:${stamp.slice(13, 15)}Z`;
  const signedAt = Date.parse(iso), seconds = Number(query['X-Amz-Expires']);
  return Number.isFinite(signedAt) && new Date(signedAt).toISOString().replace('.000', '') === iso && seconds <= 3600 && signedAt <= now + 60000 && signedAt + seconds * 1000 > now && Date.parse(expiry) <= signedAt + seconds * 1000 + 60000;
}

module.exports = { buildMarketCache, decodeCacheGroup, verifyMarketCache, verifyCompressedMarketCache, planCacheAttachments, promoteCacheRevision, validateCacheDownload };
