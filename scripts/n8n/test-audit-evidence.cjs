const test=require('node:test');const assert=require('node:assert/strict');const crypto=require('node:crypto');
const {growthFixture}=require('./growth-fixture.cjs');let evidence={};try{evidence=require('./audit-evidence.cjs');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
const expected={marketDate:'2026-10-02',requestId:'local-test',actionsRunId:'123',sourceGitCommit:'a'.repeat(40)};
function fixture(){const body={schemaVersion:'screening-export-v1',...expected,generatedAt:'2026-10-02T10:00:00Z',runId:'local-run',revision:'b'.repeat(12),formulaVersions:{ranking:'v1'},legacy:false,freshness:'current',coverage:{},funnel:growthFixture(),strategies:{trust:[{code:'0050',rank:1}],growth:[],lowPosition:[]},selectedStocks:[{code:'0050',name:'Local only',sector:'test',metrics:{currentPrice:0,ttmEps:null,growthMethod:'eps_growth'},strategies:[{strategy:'trust',rank:1,status:'ok',reason:''}],provenance:{marketDate:expected.marketDate}}]};const raw=JSON.stringify(body);return raw.slice(0,-1)+',"payloadHash":"'+crypto.createHash('sha256').update(raw).digest('hex')+'"}';}
test('modern audit evidence projects all actual numeric fields while preserving null, zero and metric text',()=>{
 assert.equal(typeof evidence.modernAuditEvidence,'function');const result=evidence.modernAuditEvidence(fixture(),expected);
 assert.equal(result.marketDate,expected.marketDate);assert.equal(result.revision,'b'.repeat(12));assert.equal(result.actionsRunId,'123');assert.equal(result.stocks.length,1);
 const stock=result.stocks[0];assert.equal(Object.keys(stock.metrics).length,16);assert.equal(stock.metrics.currentPrice,0);assert.equal(stock.metrics.ttmEps,null);assert.equal(stock.metrics.currentPe,null);assert.equal(Object.hasOwn(stock.metrics,'growthMethod'),false);assert.ok(stock.metricsJson.includes('eps_growth'));
 assert.throws(()=>evidence.modernAuditEvidence(fixture(),{...expected,sourceGitCommit:'c'.repeat(40)}),/audit_source_commit/);
 assert.throws(()=>evidence.modernAuditEvidence(fixture(),{...expected,sourceGitCommit:'invalid'}),/audit_source_commit/);
 assert.throws(()=>evidence.modernAuditEvidence(fixture(),{...expected,actionsRunId:'124'}),/lineage/);
 assert.throws(()=>evidence.modernAuditEvidence(fixture().replace('Local only','tampered'),expected),/hash/);
});
