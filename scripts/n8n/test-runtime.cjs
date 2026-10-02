const {growthFixture}=require('./growth-fixture.cjs');
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
let runtime = {};
try { runtime = require('./runtime.cjs'); } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }
function rawExport(changes = {}) {
  const body = { schemaVersion: 'screening-export-v1', marketDate: '2026-10-02', generatedAt: '2026-10-02T10:00:00Z', runId: 'run-1', requestId: 'test-1', sourceGitCommit: 'a'.repeat(40), actionsRunId: '123', revision: 'b'.repeat(12), formulaVersions: { ranking: 'v1' }, legacy: false, freshness: 'current', coverage: {}, funnel: growthFixture(1), strategies: { trust: [{ code: '0050', rank: 1 }], growth: [{ code: '0050', rank: 1 }], lowPosition: [] }, selectedStocks: [{ code: '0050', name: 'Test only', sector: '', metrics: { currentPrice: 100 }, strategies: [{ strategy: 'trust', rank: 1, status: 'ok', reason: '' }, { strategy: 'growth', rank: 1, status: 'ok', reason: '' }], provenance: { marketDate: '2026-10-02' } }], ...changes };
  const preimage = JSON.stringify(body);
  return preimage.slice(0,-1) + ',"payloadHash":"' + crypto.createHash('sha256').update(preimage).digest('hex') + '"}';
}
const expected = { marketDate: '2026-10-02', requestId: 'test-1', actionsRunId: '123' };
test('validates exact bytes and selected union with leading-zero code', () => {
  assert.equal(typeof runtime.validateExport, 'function');
  const data = runtime.validateExport(rawExport(), expected);
  assert.equal(data.selectedStocks.length, 1);
  assert.equal(data.selectedStocks[0].code, '0050');
});
test('rejects changed bytes, wrong run/date, stale input, incomplete union', () => {
  assert.equal(typeof runtime.validateExport, 'function');
  assert.throws(() => runtime.validateExport(rawExport().replace('Test only','Tampered'), expected), /hash/);
  assert.throws(() => runtime.validateExport(rawExport(), {...expected, actionsRunId:'124'}), /lineage/);
  assert.throws(() => runtime.validateExport(rawExport(), {...expected, marketDate:'2026-10-01'}), /lineage/);
  assert.throws(() => runtime.validateExport(rawExport({coverage:{universeStale:true}}),expected), /stale/);
  assert.throws(() => runtime.validateExport(rawExport({selectedStocks:[]}),expected), /union/);
});
test('legitimate zero remains an empty complete archive', () => {
  assert.equal(typeof runtime.validateExport, 'function');
  const data = runtime.validateExport(rawExport({strategies:{trust:[],growth:[],lowPosition:[]},selectedStocks:[],funnel:growthFixture()}),expected);
  assert.equal(data.selectedStocks.length,0);
});
test('Notion child schema records text codes, tags, ranks, metrics and provenance', () => {
  assert.equal(typeof runtime.stockProperties, 'function');
  const item=runtime.validateExport(rawExport(),expected).selectedStocks[0];
  const properties=runtime.stockProperties(item,{revision:'b'.repeat(12),payloadHash:'c'.repeat(64)});
  assert.equal(properties['股票代號'].rich_text[0].text.content,'0050');
  assert.deepEqual(properties['策略'].multi_select.map(x=>x.name),['trust','growth']);
  assert.equal(properties['投信排名'].number,1);
  assert.equal(properties['成長排名'].number,1);
  assert.equal(properties['低位階排名'].number,null);
  assert.equal(properties['currentPrice'].number,100);
  assert.ok(properties['來源'].rich_text[0].text.content.includes('2026-10-02'));
});
test('Notion throttle respects Retry-After seconds and HTTP dates', () => {
  assert.equal(typeof runtime.retrySeconds,'function');
  assert.equal(runtime.retrySeconds('5',0),5);
  assert.equal(runtime.retrySeconds('Thu, 01 Jan 1970 00:00:05 GMT',0),5);
  assert.equal(runtime.retrySeconds(undefined,0),2);
});
test('CAS claims never steal live or unreleased owner', () => {
  assert.equal(typeof runtime.claimState,'function');
  assert.throws(()=>runtime.claimState({owner:'other',released:false},'self'),/writer_busy/);
  assert.equal(runtime.claimState({owner:'other',released:true,stage:'artifact'},'self').stage,'artifact');
  assert.equal(runtime.claimState(null,'self').owner,'self');
});
