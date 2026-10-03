const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { gzipSync } = require('node:zlib');
let cache = {};
try { cache = require('./market-cache.cjs'); } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const date = '2026-10-02';
const prior = '2026-10-01';
const source = { requestId: 'stockscreener:20261002:v2', actionsRunId: '37094557187', sourceGitCommit: 'a'.repeat(40) };
const roles = [
  ['institutional_raw:TWSE', 'institutional_raw', 'TWSE'],
  ['institutional_raw:TPEx', 'institutional_raw', 'TPEx'],
  ['institutional_normalized:TWSE', 'institutional_normalized', 'TWSE'],
  ['institutional_normalized:TPEx', 'institutional_normalized', 'TPEx'],
  ['calendar_raw', 'calendar_raw', 'TWSE'], ['calendar_normalized', 'calendar_normalized', 'TWSE'],
  ['volume_raw', 'volume_raw', 'TWSE'], ['volume_normalized', 'volume_normalized', 'TWSE'],
  ['published_stock_inputs', 'published_stock_inputs', 'ALL'],
];
function fixture() {
  const raw = Buffer.from('exact official receipt\n0.0 中文');
  const groups = roles.map(([key, kind, market]) => {
    const codes = kind.startsWith('institutional') ? [market === 'TWSE' ? '2330' : '1240'] : kind.startsWith('volume') ? ['00631L'] : kind === 'published_stock_inputs' ? ['1240', '2330'] : [];
    const dates = kind.startsWith('institutional') || kind.startsWith('volume') ? [prior, date] : [date];
    let body = raw;
    if (kind === 'institutional_normalized') body = { rows: dates.flatMap(marketDate => codes.map(code => ({ marketDate, code, buy: 0, sell: 1000, net: -1000, unit: 'shares' }))) };
    if (kind === 'volume_normalized') body = { rows: dates.map(marketDate => ({ marketDate, code: '00631L', volume: marketDate === prior ? 0 : 2000, unit: 'shares' })) };
    if (kind === 'calendar_normalized') body = { year: 2026, timezone: 'Asia/Taipei', closedDates: ['2026-10-09'], openExceptions: ['2026-02-23'] };
    if (kind === 'published_stock_inputs') body = { rows: codes.map(code => ({ marketDate: date, code, metrics: { currentPrice: code === '1240' ? 0 : 100, currentPeg: null } })) };
    return { key, kind, market, codes, dates, ...(kind.startsWith('institutional') ? { codesByDate: Object.fromEntries(dates.map(marketDate => [marketDate, [...codes]])) } : {}), unit: kind.startsWith('calendar') ? 'calendar' : kind === 'published_stock_inputs' ? 'mixed' : 'shares', sourceUrl: 'https://openapi.twse.com.tw/v1/example', sourceSha256: hash(raw), normalizedFromSha256: kind.endsWith('_normalized') ? hash(raw) : null, body };
  });
  const expected = { marketDate: date, previousTradingDate: prior, source, metricKeys: ['currentPrice', 'currentPeg'], calendarYear: 2026, groups: groups.map(({ body, ...group }) => group) };
  const input = { marketDate: date, previousTradingDate: prior, generatedAt: '2026-10-03T04:00:00Z', source, groups };
  return { input, expected };
}
function built(input = fixture().input, limits) { return cache.buildMarketCache(input, limits); }
// Fixture trust mimics a manifest digest first obtained from an authenticated
// exact-run artifact, independently of the later Notion download being checked.
function verify(bundle, expected = fixture().expected) { return cache.verifyMarketCache(bundle.manifest, bundle.files, { manifestHash: bundle.manifest.manifestHash, ...expected }); }
function changedInput(key, change) {
  const { input, expected } = fixture();
  return { input: { ...input, groups: input.groups.map(group => group.key === key ? change(group) : group) }, expected };
}
function producerEvidence(bundle) {
  const checked = verify(bundle);
  const proof = { schemaVersion: 'market-cache-producer-proof-v1', semanticValidation: 'bounded-python-v1', marketDate: date, previousTradingDate: prior, source, cacheComplete: checked.cacheComplete, manifestHash: checked.manifestHash, groupsVerified: checked.groupsVerified, verifiedParts: checked.verifiedParts, metricsComplete: checked.metricsComplete, metricCoverage: checked.metricCoverage };
  const bytes = Buffer.from(JSON.stringify(proof));
  const expected = { ...fixture().expected, manifestHash: bundle.manifest.manifestHash, producerProofSha256: hash(bytes), artifactLineage: { repository: 'pingpongtech-uskg/stock-web-pages', workflowId: '353554563', artifactId: '11262758917', artifactSha256: 'c'.repeat(64), ...source } };
  return { proof, bytes, expected };
}

test('deterministic gzip bundle preserves exact receipts and separates metric coverage from byte completeness', () => {
  const first = built(); const second = built();
  assert.deepEqual(first, second);
  const proof = verify(first);
  assert.equal(proof.cacheComplete, true);
  assert.equal(proof.groupsVerified, 9);
  assert.deepEqual(proof.metricCoverage, { currentPrice: { known: 2, missing: 0, zero: 1 }, currentPeg: { known: 0, missing: 2, zero: 0 } });
  assert.equal(proof.metricsComplete, false);
  assert.equal(proof.manifestHash, first.manifest.manifestHash);
  assert.equal(cache.decodeCacheGroup(first.manifest.groups[0], first.files).toString(), 'exact official receipt\n0.0 中文');
});

test('gzip shards obey both compressed and inflated bounds and reassemble JSON across arbitrary byte boundaries', () => {
  const { input, expected } = fixture();
  const bundle = built(input, { maxCompressedBytes: 100, maxRawBytes: 120 });
  assert.ok(bundle.manifest.groups.some(group => group.shards.length > 1));
  for (const group of bundle.manifest.groups) for (const part of group.shards) {
    assert.ok(part.gzipBytes <= 100); assert.ok(part.rawBytes <= 120);
  }
  assert.equal(verify(bundle, expected).cacheComplete, true);
  assert.throws(() => built(input, { maxCompressedBytes: 4 * 1024 * 1024 + 1 }), /cache_limit/);
  assert.throws(() => built(input, { maxRawBytes: 32 * 1024 * 1024 + 1 }), /cache_limit/);
});

test('manifest requires all roles and independently binds dates, raw lineage, universe and Actions source', () => {
  const bundle = built(); const expected = fixture().expected;
  for (const bad of [
    { ...expected, marketDate: prior }, { ...expected, previousTradingDate: '2026-09-30' },
    { ...expected, source: { ...source, sourceGitCommit: 'b'.repeat(40) } },
    { ...expected, groups: expected.groups.map(group => group.key === 'institutional_normalized:TWSE' ? { ...group, codes: ['2330', '2317'] } : group) },
    { ...expected, groups: expected.groups.map(group => group.key === 'institutional_raw:TPEx' ? { ...group, sourceSha256: 'b'.repeat(64) } : group) },
    { ...expected, groups: expected.groups.slice(1) },
  ]) assert.throws(() => verify(bundle, bad), /cache_/);
  assert.throws(() => built({ ...fixture().input, groups: fixture().input.groups.slice(1) }), /cache_roles/);
  assert.throws(() => built({ ...fixture().input, source: { ...source, actionsRunId: 'legacy' } }), /cache_lineage/);
  assert.throws(() => built({ ...fixture().input, previousTradingDate: date }), /cache_dates/);
});

test('missing, extra, duplicate or wrong-date rows never masquerade as a complete market', () => {
  const mutations = [
    group => ({ ...group, body: { rows: group.body.rows.slice(1) } }),
    group => ({ ...group, body: { rows: [...group.body.rows, group.body.rows[0]] } }),
    group => ({ ...group, body: { rows: group.body.rows.map(row => ({ ...row, marketDate: '2026-09-30' })) } }),
    group => ({ ...group, body: { rows: group.body.rows.map(row => ({ ...row, code: '9999' })) } }),
  ];
  for (const mutation of mutations) {
    const { input, expected } = changedInput('institutional_normalized:TPEx', mutation);
    assert.throws(() => verify(built(input), expected), /cache_coverage/);
  }
});

test('institutional units and numeric equality fail closed; genuine zero survives', () => {
  for (const values of [{ buy: null }, { buy: 0.5 }, { sell: -1 }, { net: 0 }, { unit: 'lots' }]) {
    const { input, expected } = changedInput('institutional_normalized:TWSE', group => ({ ...group, body: { rows: group.body.rows.map(row => ({ ...row, ...values })) } }));
    assert.throws(() => verify(built(input), expected), /cache_(units|numbers)/);
  }
  const { input, expected } = changedInput('institutional_normalized:TWSE', group => ({ ...group, body: { rows: group.body.rows.map(row => ({ ...row, buy: 0, sell: 0, net: 0 })) } }));
  assert.equal(verify(built(input), expected).cacheComplete, true);
});

test('published inputs require explicit number/null metrics and calendar/reference coverage', () => {
  for (const metrics of [{ currentPrice: 1 }, { currentPrice: '0', currentPeg: null }, { currentPrice: Infinity, currentPeg: null }, { currentPrice: 1, currentPeg: null, token: 'bad' }]) {
    const { input, expected } = changedInput('published_stock_inputs', group => ({ ...group, body: { rows: group.body.rows.map(row => ({ ...row, metrics })) } }));
    assert.throws(() => verify(built(input), expected), /cache_(metrics|numbers|secret)/);
  }
  const volume = changedInput('volume_normalized', group => ({ ...group, body: { rows: group.body.rows.slice(1) } }));
  assert.throws(() => verify(built(volume.input), volume.expected), /cache_coverage/);
  const calendar = changedInput('calendar_normalized', group => ({ ...group, body: { ...group.body, year: 2025 } }));
  assert.throws(() => verify(built(calendar.input), calendar.expected), /cache_calendar/);
});

test('manifest/shard tampering, missing/extra binaries and gzip bombs cannot pass readback', () => {
  const bundle = built(); const name = Object.keys(bundle.files)[0];
  assert.throws(() => verify({ ...bundle, manifest: { ...bundle.manifest, generatedAt: '2026-10-04T00:00:00Z' } }), /cache_manifest_hash/);
  assert.throws(() => verify({ ...bundle, files: { ...bundle.files, [name]: Buffer.from('corrupt') } }), /cache_(gzip_hash|gzip_size)/);
  const { [name]: removed, ...rest } = bundle.files;
  assert.throws(() => verify({ ...bundle, files: rest }), /cache_files/);
  assert.throws(() => verify({ ...bundle, files: { ...bundle.files, extra: Buffer.alloc(1) } }), /cache_files/);
  const bomb = gzipSync(Buffer.alloc(32 * 1024 * 1024 + 1));
  const group = { ...bundle.manifest.groups[0], rawBytes: 1, shards: [{ name, index: 0, gzipBytes: bomb.length, gzipSha256: hash(bomb), rawBytes: 1, rawSha256: hash(Buffer.alloc(1)) }] };
  assert.throws(() => cache.decodeCacheGroup(group, { [name]: bomb }), /cache_inflate_limit/);
});

test('readback requires an independently authenticated manifest digest, not just a self hash', () => {
  const bundle = built();
  assert.throws(() => cache.verifyMarketCache(bundle.manifest, bundle.files, fixture().expected), /cache_expected_manifest/);
  assert.throws(() => verify(bundle, { ...fixture().expected, manifestHash: 'b'.repeat(64) }), /cache_expected_manifest/);
});

test('decoder rejects descriptor expansion budgets and path names before decompression', () => {
  const bundle = built(); const group = bundle.manifest.groups[0];
  assert.throws(() => cache.decodeCacheGroup({ ...group, rawBytes: 1, shards: group.shards.map(part => ({ ...part, rawBytes: 32 * 1024 * 1024 })) }, bundle.files), /cache_raw_size/);
  assert.throws(() => cache.decodeCacheGroup({ ...group, shards: group.shards.map(part => ({ ...part, name: '../cache.json.gz' })) }, bundle.files), /cache_filename/);
  const count = { ...group.shards[0], rawBytes: 32 * 1024 * 1024 };
  assert.throws(() => cache.decodeCacheGroup({ ...group, rawBytes: 9 * count.rawBytes, shards: Array.from({ length: 9 }, (_, index) => ({ ...count, index })) }, bundle.files), /cache_raw_size/);
});

test('duplicate logical attachments reuse existing uploads, preserve active revision until full readback', () => {
  const bundle = built(); const names = Object.keys(bundle.files);
  const priorFile = { name: 'old-cache.json.gz', uploadId: 'old-id' };
  const uploads = names.map((name, i) => ({ name, uploadId: `new-${i}` }));
  const existing = [priorFile, uploads[0], { ...uploads[0], uploadId: 'duplicate-upload' }];
  const plan = cache.planCacheAttachments(existing, uploads, bundle.manifest);
  assert.equal(plan.files.length, names.length + 1);
  assert.equal(plan.files.find(file => file.name === names[0]).uploadId, 'new-0');
  assert.deepEqual(cache.planCacheAttachments(plan.files, uploads, bundle.manifest).files, plan.files);
  const current = { activeManifestHash: 'f'.repeat(64), revisionHashes: ['f'.repeat(64)] };
  assert.deepEqual(cache.promoteCacheRevision(current, bundle.manifest, { cacheComplete: false }), current);
  assert.deepEqual(cache.promoteCacheRevision(current, bundle.manifest, { ...verify(bundle), manifestHash: 'e'.repeat(64) }), current);
  const next = cache.promoteCacheRevision(current, bundle.manifest, verify(bundle));
  assert.equal(next.activeManifestHash, bundle.manifest.manifestHash);
  assert.equal(next.revisionHashes.length, 2);
  assert.deepEqual(current.revisionHashes, ['f'.repeat(64)]);
  assert.deepEqual(cache.promoteCacheRevision(next, bundle.manifest, verify(bundle)), next);
  assert.throws(() => cache.planCacheAttachments([], [], bundle.manifest), /cache_uploads_missing/);
});

test('Notion cache downloads accept only fresh known storage origin with anonymous nonredirect binary transport', () => {
  const file = { url: 'https://s3.us-west-2.amazonaws.com/secure.notion-static.com/abc/cache.json.gz?X-Amz-Date=20261003T040000Z&X-Amz-Expires=3600&X-Amz-Signature=abc', expiry_time: '2026-10-03T05:00:00Z' };
  const policy = { authentication: 'none', followRedirects: false, responseFormat: 'file' };
  assert.equal(cache.validateCacheDownload(file, policy, '2026-10-03T04:00:00Z'), true);
  for (const url of ['https://evil.example/cache.gz', 'https://s3.us-west-2.amazonaws.com.evil/secure.notion-static.com/a', 'https://user@s3.us-west-2.amazonaws.com/secure.notion-static.com/a', 'https://s3.us-west-2.amazonaws.com:443/secure.notion-static.com/a', 'https://s3.us-west-2.amazonaws.com/secure.notion-static.com/../a', 'https://s3.us-west-2.amazonaws.com/secure.notion-static.com/%2e%2e/a']) assert.throws(() => cache.validateCacheDownload({ ...file, url }, policy), /cache_storage/);
  assert.throws(() => cache.validateCacheDownload(file, policy, '2026-10-03T06:00:00Z'), /cache_url_expired/);
  for (const bad of [{ ...policy, authentication: 'notionApi' }, { ...policy, followRedirects: true }, { ...policy, responseFormat: 'json' }]) assert.throws(() => cache.validateCacheDownload(file, bad, '2026-10-03T04:00:00Z'), /cache_download_policy/);
  for (const extra of [{ headers: { Authorization: 'Bearer dummy' } }, { cookies: 'dummy' }, { sendHeaders: true }, { url: 'https://evil.example' }]) assert.throws(() => cache.validateCacheDownload(file, { ...policy, ...extra }, '2026-10-03T04:00:00Z'), /cache_download_policy/);
});

test('source receipt URLs reject credential queries/fragments while retaining ordinary official date parameters', () => {
  for (const suffix of ['?access_token=dummy', '?sig=dummy', '?apiKey=dummy', '?%74oken=dummy', '#secret', '?X-Amz-Credential=dummy']) {
    const { input } = changedInput('institutional_raw:TWSE', group => ({ ...group, sourceUrl: group.sourceUrl + suffix }));
    assert.throws(() => built(input), /cache_source_url/);
  }
  const { input, expected } = fixture();
  const change = group => ({ ...group, sourceUrl: group.sourceUrl + '?d=115%2F10%2F02&l=zh-tw' });
  assert.equal(verify(built({ ...input, groups: input.groups.map(change) }), { ...expected, groups: expected.groups.map(change) }).cacheComplete, true);
});

test('calendar and published inputs declare their actual units rather than a share-conversion assumption', () => {
  for (const key of ['calendar_raw', 'calendar_normalized', 'published_stock_inputs']) {
    const { input } = changedInput(key, group => ({ ...group, unit: 'lots' }));
    assert.throws(() => built(input), /cache_units/);
  }
});

test('institutional membership is exact per session; a prior-only code is never filled with invented zero', () => {
  const { input, expected } = fixture();
  const codesByDate = { [prior]: ['1240', '3105'], [date]: ['1240'] };
  const changes = group => group.kind.startsWith('institutional') && group.market === 'TPEx' ? {
    ...group, codes: ['1240', '3105'], codesByDate,
    ...(group.kind === 'institutional_normalized' ? { body: { rows: Object.entries(codesByDate).flatMap(([marketDate, codes]) => codes.map(code => ({ marketDate, code, buy: 0, sell: 0, net: 0, unit: 'shares' }))) } } : {}),
  } : group;
  const changed = { ...input, groups: input.groups.map(changes) };
  const trusted = { ...expected, groups: expected.groups.map(changes) };
  assert.equal(verify(built(changed), trusted).cacheComplete, true);
  const filler = { ...changed, groups: changed.groups.map(group => group.key === 'institutional_normalized:TPEx' ? { ...group, body: { rows: [...group.body.rows, { marketDate: date, code: '3105', buy: 0, sell: 0, net: 0, unit: 'shares' }] } } : group) };
  assert.throws(() => verify(built(filler), trusted), /cache_coverage/);
  const drift = { ...trusted, groups: trusted.groups.map(group => group.kind.startsWith('institutional') && group.market === 'TPEx' ? { ...group, codesByDate: { ...codesByDate, [date]: ['3105'] } } : group) };
  assert.throws(() => verify(built(changed), drift), /cache_expected_group/);
});

test('institutional codesByDate cannot omit a date, repeat codes or disagree with the union', () => {
  for (const codesByDate of [undefined, { [date]: ['1240'] }, { [prior]: ['1240'], [date]: ['1240', '1240'] }, { [prior]: ['1240'], [date]: ['3105'] }]) {
    const { input } = changedInput('institutional_normalized:TPEx', group => ({ ...group, codesByDate }));
    assert.throws(() => built(input), /cache_membership/);
  }
});

test('compressed backup verifies authenticated producer proof and exact gzip bytes without importing zlib', () => {
  const bundle = built(); const { bytes, expected } = producerEvidence(bundle);
  const proof = cache.verifyCompressedMarketCache(bundle.manifest, bundle.files, expected, bytes);
  assert.equal(proof.verificationLevel, 'compressed_backup_verified');
  assert.equal(proof.cacheComplete, true);
  assert.equal(proof.rawSemanticsVerifiedByProducer, true);
  assert.equal(proof.independentRawSemanticsVerified, false);
  assert.equal(proof.metricsComplete, false);
  const fs = require('node:fs'); const vm = require('node:vm'); const imported = [];
  const sandbox = { Buffer, result: null, module: { exports: {} }, require: name => { imported.push(name); if (name.includes('zlib')) throw Error('zlib unavailable'); return require(name); }, bundleJson: JSON.stringify(bundle.manifest), filesJson: JSON.stringify(Object.fromEntries(Object.entries(bundle.files).map(([name, binary]) => [name, binary.toString('base64')]))), expectedJson: JSON.stringify(expected), proofJson: bytes.toString('utf8') };
  vm.runInNewContext(fs.readFileSync(require.resolve('./market-cache.cjs'), 'utf8') + '\nresult=module.exports.verifyCompressedMarketCache(JSON.parse(bundleJson),Object.fromEntries(Object.entries(JSON.parse(filesJson)).map(([name, data])=>[name,Buffer.from(data,"base64")])),JSON.parse(expectedJson),Buffer.from(proofJson));', sandbox);
  assert.equal(sandbox.result.verificationLevel, 'compressed_backup_verified');
  assert.equal(imported.some(name => name.includes('zlib')), false);
});

test('compressed backup rejects selfdeclared proof without external hash and exact Actions artifact lineage', () => {
  const bundle = built(); const { bytes, expected } = producerEvidence(bundle);
  for (const bad of [
    { ...expected, artifactLineage: undefined }, { ...expected, producerProofSha256: undefined },
    { ...expected, artifactLineage: { ...expected.artifactLineage, actionsRunId: '9' } },
    { ...expected, artifactLineage: { ...expected.artifactLineage, sourceGitCommit: 'b'.repeat(40) } },
    { ...expected, artifactLineage: { ...expected.artifactLineage, repository: 'other/repo' } },
  ]) assert.throws(() => cache.verifyCompressedMarketCache(bundle.manifest, bundle.files, bad, bytes), /cache_producer_auth/);
  assert.throws(() => cache.verifyCompressedMarketCache(bundle.manifest, bundle.files, expected, Buffer.from(bytes.toString() + ' ')), /cache_producer_hash/);
});

test('compressed backup rejects partial producer proof, bad metric counts and false coverage declarations', () => {
  const bundle = built(); const evidence = producerEvidence(bundle);
  for (const change of [{ cacheComplete: false }, { semanticValidation: 'self-claimed' }, { groupsVerified: 8 }, { verifiedParts: [] }, { source: { ...source, requestId: 'different' } }, { metricsComplete: true }, { metricCoverage: { ...evidence.proof.metricCoverage, currentPrice: { known: 2, missing: 0, zero: 3 } } }]) {
    const bytes = Buffer.from(JSON.stringify({ ...evidence.proof, ...change }));
    assert.throws(() => cache.verifyCompressedMarketCache(bundle.manifest, bundle.files, { ...evidence.expected, producerProofSha256: hash(bytes) }, bytes), /cache_producer_/);
  }
});

test('compressed backup verifies gzip header and ISIZE declaration without inflating or advancing on mismatch', () => {
  const bundle = built(); const { bytes, expected } = producerEvidence(bundle);
  const name = Object.keys(bundle.files)[0];
  assert.throws(() => cache.verifyCompressedMarketCache(bundle.manifest, { ...bundle.files, [name]: Buffer.from('bad') }, expected, bytes), /cache_gzip_/);
  const original = bundle.manifest.groups[0].shards[0];
  const bad = Buffer.from(bundle.files[name]); bad.writeUInt32LE(original.rawBytes + 1, bad.length - 4);
  const shard = { ...original, gzipSha256: hash(bad) };
  const manifest = { ...bundle.manifest, groups: bundle.manifest.groups.map((group, i) => i === 0 ? { ...group, shards: [shard] } : group) };
  const canonical = value => value && typeof value === 'object' ? Array.isArray(value) ? '[' + value.map(canonical).join(',') + ']' : '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}' : JSON.stringify(value);
  const { manifestHash, ...body } = manifest; const corrected = { ...manifest, manifestHash: hash(canonical(body)) };
  const proof = { ...producerEvidence(bundle).proof, manifestHash: corrected.manifestHash };
  const proofBytes = Buffer.from(JSON.stringify(proof));
  const result = () => cache.verifyCompressedMarketCache(corrected, { ...bundle.files, [name]: bad }, { ...expected, manifestHash: corrected.manifestHash, producerProofSha256: hash(proofBytes) }, proofBytes);
  assert.throws(result, /cache_gzip_isize/);
  assert.equal(cache.promoteCacheRevision({ activeManifestHash: 'f'.repeat(64), revisionHashes: ['f'.repeat(64)] }, bundle.manifest, { cacheComplete: false }).activeManifestHash, 'f'.repeat(64));
});

test('canonical artifact source/map key order does not break exact semantic lineage binding', () => {
  const bundle = built(); const { bytes, expected } = producerEvidence(bundle);
  const manifest = { ...bundle.manifest, source: Object.fromEntries(Object.entries(source).sort(([a], [b]) => a.localeCompare(b))) };
  assert.equal(cache.verifyCompressedMarketCache(manifest, bundle.files, expected, bytes).verificationLevel, 'compressed_backup_verified');
  const reverse = { ...expected, groups: expected.groups.map(group => group.codesByDate ? { ...group, codesByDate: Object.fromEntries(Object.entries(group.codesByDate).reverse()) } : group) };
  assert.equal(cache.verifyCompressedMarketCache(manifest, bundle.files, reverse, bytes).cacheComplete, true);
});

test('observed Notion virtual-host storage is exact and signed expiry/path/query remain bounded', () => {
  const policy={authentication:'none',followRedirects:false,responseFormat:'file'};const now='2026-10-03T04:00:00Z';
  const base='https://prod-files-secure.s3.us-west-2.amazonaws.com/abc/cache.json.gz';const query='?X-Amz-Date=20261003T040000Z&X-Amz-Expires=3600&X-Amz-Signature=abc';const file={url:base+query,expiry_time:'2026-10-03T05:00:00Z'};
  assert.equal(cache.validateCacheDownload(file,policy,now),true);
  for(const url of [base.replace('prod-files-secure.','other.')+query,base.replace('.amazonaws.com','.amazonaws.com.evil')+query,base.replace('https://','https://user@')+query,base.replace('.com/','.com:443/')+query,base.replace('/abc/','/../')+query,base.replace('/abc/','/%2e%2e/')+query,base+query+'&X-Amz-Expires=3600',base+query.replace('Expires=3600','Expires=86400'),base+query.replace('T040000Z','T020000Z'),base+query.replace('X-Amz-Date','Missing-Date'),base+query+'#secret'])assert.throws(()=>cache.validateCacheDownload({...file,url},policy,now),/cache_storage|cache_url_expired/);
});
