const test=require('node:test');const assert=require('node:assert/strict');const crypto=require('node:crypto');
let legacy={};try{legacy=require('./legacy.cjs');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
const body={schemaVersion:'screening-history-record-v1',legacy:true,marketDate:'2026-09-08',generatedAt:'2026-09-08T10:00:00Z',revision:'a'.repeat(12),runId:'retained-original',freshness:'degraded',formulaVersions:{},funnel:{},sourceRefs:['original-file.json'],strategies:{trust:[{code:'0050',name:'Local legacy fixture',sector:'',rank:1,status:'historical',reason:'',currentPrice:123}],growth:[{code:'0050',name:'Local legacy fixture',sector:'',rank:1,status:'historical',reason:'',growthFairPrice:140}],lowPosition:[]}};
const raw=JSON.stringify(body);const hash=crypto.createHash('sha256').update(raw).digest('hex');const expected={marketDate:body.marketDate,revision:body.revision,runId:body.runId,sha256:hash,archiveCommit:'b'.repeat(40)};
test('legacy adapter retains original evidence and deduplicates actual union with absent metrics null',()=>{
 assert.equal(typeof legacy.validateLegacyArchive,'function');const projection=legacy.validateLegacyArchive(raw,expected);
 assert.equal(projection.selectedStocks.length,1);assert.equal(projection.selectedStocks[0].code,'0050');
 assert.equal(projection.selectedStocks[0].metrics.currentPrice,123);assert.equal(projection.selectedStocks[0].metrics.growthFairPrice,140);
 assert.equal(projection.selectedStocks[0].metrics.ttmEps,null);assert.equal(projection.sourceGitCommit,'');assert.equal(projection.actionsRunId,'');
 assert.equal(projection.payloadHash,hash);assert.equal(projection.selectedStocks[0].provenance.valuationEvidenceLevel,'legacy_archive');
});
test('legacy adapter rejects tampering, wrong date/ref, nonlegacy records and duplicate ranks',()=>{
 assert.equal(typeof legacy.validateLegacyArchive,'function');assert.throws(()=>legacy.validateLegacyArchive(raw+' ',expected),/hash/);
 assert.throws(()=>legacy.validateLegacyArchive(raw,{...expected,marketDate:'2026-09-11'}),/lineage/);
 const check=value=>{const bytes=JSON.stringify(value);return legacy.validateLegacyArchive(bytes,{...expected,sha256:crypto.createHash('sha256').update(bytes).digest('hex')});};
 assert.throws(()=>check({...body,legacy:false}),/schema/);
 assert.throws(()=>check({...body,strategies:{...body.strategies,trust:[...body.strategies.trust,...body.strategies.trust]}}),/duplicates/);
});
module.exports={raw,expected};
test('six real retained active revisions validate directly from immutable repository evidence',()=>{
 const fs=require('node:fs');const path=require('node:path');const data=path.resolve(__dirname,'../../public/data');
 const index=JSON.parse(fs.readFileSync(path.join(data,'archive/v1/index.json'),'utf8'));let dates=[];
 for(const month of index.months){const monthRaw=fs.readFileSync(path.join(data,month.path.replace('/data/','')),'utf8');assert.equal(crypto.createHash('sha256').update(monthRaw).digest('hex'),month.sha256);
 for(const record of JSON.parse(monthRaw).records){if(!record.legacy)continue;const ref=record.revisionRefs.find(item=>item.revision===record.revision);const bytes=fs.readFileSync(path.join(data,ref.path.replace('/data/','')),'utf8');
 const p=legacy.validateLegacyArchive(bytes,{marketDate:record.marketDate,revision:record.revision,runId:record.runId,sha256:ref.sha256,archiveCommit:'b'.repeat(40)});assert.equal(p.legacy,true);dates.push(p.marketDate);}}
 assert.deepEqual(dates.sort(),['2026-09-08','2026-09-11','2026-09-18','2026-09-23','2026-09-24','2026-10-01']);
});
test('legacy projection rejects malformed stocks/schema and retains legitimate empty union',()=>{
 const check=value=>{const bytes=JSON.stringify(value);return legacy.validateLegacyArchive(bytes,{...expected,sha256:crypto.createHash('sha256').update(bytes).digest('hex')});};
 assert.throws(()=>check({...body,strategies:{trust:[]}}),/strategy_schema/);
 assert.throws(()=>check({...body,strategies:{...body.strategies,trust:[{...body.strategies.trust[0],code:'bad'}]}}),/stock_schema/);
 assert.throws(()=>check({...body,strategies:{...body.strategies,trust:[{...body.strategies.trust[0],currentPrice:'123'}]}}),/metric_schema/);
 const zero=check({...body,strategies:{trust:[],growth:[],lowPosition:[]}});assert.equal(zero.selectedStocks.length,0);
 assert.throws(()=>legacy.validateLegacyArchive(raw,{...expected,archiveCommit:'bad'}),/schema/);
 const optional=check({...body,sourceRefs:undefined,formulaVersions:undefined,funnel:undefined,freshness:undefined,strategies:{trust:[{...body.strategies.trust[0],sector:undefined,status:undefined,reason:undefined}],growth:[],lowPosition:[]}});
 assert.equal(optional.selectedStocks[0].sector,'');assert.equal(optional.selectedStocks[0].strategies[0].status,'unknown');
});
