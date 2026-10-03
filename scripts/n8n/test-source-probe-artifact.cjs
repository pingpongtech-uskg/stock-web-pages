const test=require('node:test');const assert=require('node:assert/strict');const crypto=require('node:crypto');
let artifact={};try{artifact=require('./source-probe-artifact.cjs');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
const dates=['2026-09-18','2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-25','2026-09-28','2026-09-29','2026-09-30','2026-10-01','2026-10-02'];
const state={plan:{requestId:'institutional-probe:local',marketDate:dates.at(-1),probeHeadSha:'a'.repeat(40)},runId:'123',runAttempt:1};
const provenance={requestId:state.plan.requestId,marketDate:state.plan.marketDate,sourceMode:'institutional_probe',sourceGitCommit:state.plan.probeHeadSha,actionsRunId:'123',actionsRunAttempt:'1',repository:'pingpongtech-uskg/stock-web-pages'};
const cases=['positive','negative','zero'].map((label,index)=>({code:String(1234+index),case:label,buy:index===0?2:0,sell:index===1?1:0,net:index===0?2:index===1?-1:0,status:'complete',coverage:1,missingDates:[],errorCategory:null}));
const summary={probeVersion:'institutional-probe-v1',marketDate:state.plan.marketDate,expectedDates:dates,publicationEligible:false,globalCompleteness:false,tokenPresent:true,actualAttempts:4,dataRequests:3,cacheHits:0,accountLimit:600,observedRemaining:500,dailyAttempts:4,projectCeiling:300,accountWindowCeiling:300,outcome:'complete',errorCategory:null,cases,officialSourceUrl:'https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading',officialRowCount:910,officialSha256:'b'.repeat(64)};
const body=(s=summary,p=provenance)=>({'summary.json':s,'provenance.json':p,byteHashes:{summary:'c'.repeat(64),provenance:'d'.repeat(64)}});
test('probe evidence binds exact lineage and preserves restricted three-case outcome without global publication claim',()=>{const out=artifact.sourceValidateArtifact(body(),state);assert.equal(out.summary.cases.length,3);assert.equal(out.summary.cases[2].net,0);assert.equal(out.summary.globalCompleteness,false);assert.deepEqual(out.byteHashes,body().byteHashes);});
test('unavailable official source permits no fake cases or quota claims; partial never means complete',()=>{
 const empty={probeVersion:summary.probeVersion,marketDate:summary.marketDate,expectedDates:dates,publicationEligible:false,globalCompleteness:false,tokenPresent:false,actualAttempts:0,dataRequests:0,cacheHits:0,accountLimit:null,observedRemaining:null,outcome:'unavailable',errorCategory:'official_source_unavailable',cases:[]};assert.equal(artifact.sourceValidateArtifact(body(empty),state).summary.cases.length,0);
 const partial={...summary,outcome:'partial',cases:cases.map(item=>({...item,status:'partial',coverage:1/11,missingDates:dates.slice(0,-1)}))};assert.equal(artifact.sourceValidateArtifact(body(partial),state).summary.outcome,'partial');
});
test('invalid provenance/schema/quota/coverage or unexpected secret fields fail closed',()=>{
 for(const key of Object.keys(provenance))assert.throws(()=>artifact.sourceValidateArtifact(body(summary,{...provenance,[key]:'wrong'}),state));
 for(const change of [{globalCompleteness:true},{publicationEligible:true},{token:'private'},{dataRequests:4},{actualAttempts:5},{dailyAttempts:301},{projectCeiling:301},{cacheHits:4},{expectedDates:dates.slice(1)},{observedRemaining:601},{cases:cases.slice(1)},{outcome:'partial'},{officialSourceUrl:'https://attacker.test'}, {cases:cases.map(item=>({...item,coverage:0.5}))},{cases:cases.map(item=>({...item,buy:1.2}))}])assert.throws(()=>artifact.sourceValidateArtifact(body({...summary,...change}),state));
 assert.throws(()=>artifact.sourceValidateArtifact({...body(),byteHashes:{summary:'bad',provenance:'d'.repeat(64)}},state));
});
test('artifact ZIP metadata allows exactly two flat trusted paths and bounded buffers; hashes are exact raw bytes',async()=>{
 const raw=Buffer.from(JSON.stringify(summary).replace('"buy":2','"buy":2.0')+'\n');const prov=Buffer.from(JSON.stringify(provenance));const files={a:{fileName:'summary.json'},b:{fileName:'provenance.json'}};const read=async key=>key==='a'?raw:prov;
 const parsed=await artifact.sourceReadArtifact(files,read);assert.equal(parsed.byteHashes.summary,crypto.createHash('sha256').update(raw).digest('hex'));assert.equal(artifact.sourceValidateArtifact(parsed,state).summary.cases[0].buy,2);
 for(const malicious of [{...files,a:{fileName:'../summary.json'}},{...files,a:{fileName:'/summary.json'}},{...files,c:{fileName:'token.txt'}},{a:{fileName:'summary.json'},b:{fileName:'summary.json'}}])await assert.rejects(artifact.sourceReadArtifact(malicious,read));
 await assert.rejects(artifact.sourceReadArtifact(files,async()=>Buffer.alloc(1000001)));await assert.rejects(artifact.sourceReadArtifact(files,async()=>Buffer.from('bad JSON')));
});
test('retained tighter project budget is respected, cached cases cannot also consume extra sample requests',()=>{assert.equal(artifact.sourceValidateArtifact(body({...summary,projectCeiling:299}),state).summary.projectCeiling,299);assert.throws(()=>artifact.sourceValidateArtifact(body({...summary,cacheHits:1}),state));});
function hourlySummary(value=summary){const {dailyAttempts,projectCeiling,accountWindowCeiling,...rest}=value;return {...rest,quotaPolicy:'rolling-hour-v1',rollingHourAttempts:4,projectHourlyCap:300,accountAllowanceRemaining:476,quotaObservedAt:'2026-10-03T04:00:00.123456+00:00'};}
test('rolling-hour summary preserves account allowance and accepts a run crossing the rolling window',()=>{
 const parsed=artifact.sourceValidateArtifact(body(hourlySummary()),state).summary;
 assert.equal(parsed.quotaPolicy,'rolling-hour-v1');assert.equal(parsed.accountAllowanceRemaining,476);
 assert.equal(Object.hasOwn(parsed,'dailyAttempts'),false);
 assert.equal(artifact.sourceValidateArtifact(body({...hourlySummary(),rollingHourAttempts:1}),state).summary.actualAttempts,4);
 assert.equal(artifact.sourceValidateArtifact(body({...hourlySummary(),accountAllowanceRemaining:450,projectHourlyCap:100,quotaObservedAt:'2026-10-03T04:00:00Z'}),state).summary.accountAllowanceRemaining,450);
});
test('rolling-hour unavailable artifact keeps quota unknown without inventing account data',()=>{
 const unavailable={probeVersion:summary.probeVersion,marketDate:summary.marketDate,expectedDates:dates,publicationEligible:false,globalCompleteness:false,tokenPresent:true,actualAttempts:0,dataRequests:0,cacheHits:0,accountLimit:null,observedRemaining:null,outcome:'unavailable',errorCategory:'official_source_unavailable',cases:[]};
 const parsed=artifact.sourceValidateArtifact(body({...hourlySummary(unavailable),rollingHourAttempts:0,accountAllowanceRemaining:null,quotaObservedAt:null}),state).summary;
 assert.equal(parsed.quotaObservedAt,null);assert.deepEqual(parsed.cases,[]);
});
test('rolling-hour schema rejects mixed legacy metadata, unversioned fields and invalid quota boundaries',()=>{
 for(const change of [{quotaPolicy:'daily-v1'},{rollingHourAttempts:-1},{rollingHourAttempts:301},{rollingHourAttempts:1.2},{projectHourlyCap:0},{projectHourlyCap:301},{accountAllowanceRemaining:-1},{accountAllowanceRemaining:1.2},{quotaObservedAt:'2026-10-03T04:00:00'},{quotaObservedAt:'2026-10-03T12:00:00+08:00'},{quotaObservedAt:'bad'},...['dailyAttempts','projectCeiling','accountWindowCeiling'].map(key=>({[key]:4}))])assert.throws(()=>artifact.sourceValidateArtifact(body({...hourlySummary(),...change}),state));
 for(const key of ['quotaPolicy','rollingHourAttempts','projectHourlyCap','accountAllowanceRemaining','quotaObservedAt']){const {[key]:omitted,...rest}=hourlySummary();assert.throws(()=>artifact.sourceValidateArtifact(body(rest),state));}
 assert.equal(artifact.sourceValidateArtifact(body(summary),state).summary.dailyAttempts,4);
});
test('corrupt checkpoint preserves unknown rolling usage only for the exact no-request unavailable outcome',()=>{
 const unavailable={probeVersion:summary.probeVersion,marketDate:summary.marketDate,expectedDates:dates,publicationEligible:false,globalCompleteness:false,tokenPresent:true,actualAttempts:0,dataRequests:0,cacheHits:0,accountLimit:null,observedRemaining:null,outcome:'unavailable',errorCategory:'checkpoint_unavailable',cases:[]};
 const corrupt={...hourlySummary(unavailable),rollingHourAttempts:null,accountAllowanceRemaining:null,quotaObservedAt:null};
 assert.equal(artifact.sourceValidateArtifact(body(corrupt),state).summary.rollingHourAttempts,null);
 for(const change of [{outcome:'complete',cases},{errorCategory:'official_source_unavailable'},{errorCategory:null},{actualAttempts:1},{dataRequests:1},{cacheHits:1},{accountAllowanceRemaining:0},{quotaObservedAt:'2026-10-03T04:00:00Z'},{projectHourlyCap:299}])assert.throws(()=>artifact.sourceValidateArtifact(body({...corrupt,...change}),state));
 const {errorCategory:omitted,...missingError}=corrupt;assert.throws(()=>artifact.sourceValidateArtifact(body(missingError),state));
 assert.throws(()=>artifact.sourceValidateArtifact(body({...hourlySummary(),rollingHourAttempts:null}),state));
});
