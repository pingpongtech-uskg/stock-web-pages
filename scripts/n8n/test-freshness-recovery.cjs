const test=require('node:test');
const assert=require('node:assert/strict');
let planFreshnessRecovery,publicationFreshnessEvidence;
try {({planFreshnessRecovery,publicationFreshnessEvidence}=require('./freshness-recovery.cjs'));}
catch(error) {if(error.code!=='MODULE_NOT_FOUND')throw error;}

const generated=Date.parse('2026-10-16T10:00:00.000Z');
function existing(overrides={}) {
 return {released:true,marketDate:'2026-10-16',requestId:'stockscreener:20261016:v1',
  screeningStatus:'complete',publicationStatus:'verified',deployStatus:'verified',
  publicationFreshness:'degraded',publicationGeneratedAt:'2026-10-16T10:00:00.000Z',
  publicationFreshnessGaps:{price:['2330'],regression:[],institution:[]},...overrides};
}
function incoming(overrides={}) {
 return {runKind:'scheduled',mode:'screen',automaticRequestId:true,marketDate:'2026-10-16',
  requestId:'stockscreener:20261016:v1',...overrides};
}
function plan(old=existing(),input=incoming(),now=generated+30*60000) {
 assert.equal(typeof planFreshnessRecovery,'function');
 return planFreshnessRecovery(old,input,now);
}

test('eligible degraded publication plans a deterministic next revision without mutating inputs',()=>{
 const old=existing(),input=incoming();const before=JSON.stringify({old,input});
 assert.deepEqual(plan(old,input),{mode:'revision',requestId:'stockscreener:20261016:refresh1',
  freshnessRefreshCount:1,previousPublishedRequestId:old.requestId});
 assert.deepEqual(plan(old,input),plan(old,input));
 assert.equal(JSON.stringify({old,input}),before);
});
test('each actionable day-data gap can independently initiate recovery',()=>{
 for(const key of ['price','regression','institution']) {
  const gaps={price:[],regression:[],institution:[],[key]:['2330']};
  assert.ok(plan(existing({publicationFreshnessGaps:gaps})));
 }
 assert.equal(plan(existing({publicationFreshnessGaps:{price:[],regression:[],institution:[]}})),null);
});
test('recovery waits thirty minutes since actual publication generation',()=>{
 assert.equal(plan(existing(),incoming(),generated+30*60000-1),null);
 assert.ok(plan(existing(),incoming(),generated+30*60000));
 assert.equal(plan(existing(),incoming(),generated-1),null);
});
test('counter permits at most six deterministic refreshes per day',()=>{
 for(let count=0;count<6;count++) {
  const result=plan(existing({freshnessRefreshCount:count,requestId:`stockscreener:20261016:refresh${count}`}));
  assert.equal(result.requestId,`stockscreener:20261016:refresh${count+1}`);
  assert.equal(result.freshnessRefreshCount,count+1);
 }
 assert.equal(plan(existing({freshnessRefreshCount:6})),null);
 for(const count of [null,-1,1.5,'1',true,7,NaN,Infinity]) {
  assert.equal(plan(existing({freshnessRefreshCount:count})),null);
 }
});
test('active writer and unverified website or screening cannot initiate another producer',()=>{
 for(const change of [{released:false},{released:undefined},{screeningStatus:'pending'},
  {screeningStatus:'failed'},{publicationStatus:'pending'},{deployStatus:'pending'},
  {deployStatus:'failed'},{publicationFreshness:'fresh'},{publicationFreshness:undefined}]) {
  assert.equal(plan(existing(change)),null);
 }
});
test('manual explicit and resume requests never initiate automatic freshness revisions',()=>{
 for(const change of [{runKind:'manual'},{mode:'resume'},{mode:'diagnose'},{mode:'revision'},
  {automaticRequestId:false},{automaticRequestId:undefined},{automaticRequestId:'true'},
  {marketDate:'2026-10-15'},{marketDate:undefined},{requestId:'invalid id'}]) {
  assert.equal(plan(existing(),incoming(change)),null);
 }
 assert.ok(plan(existing(),incoming({requestId:'stockscreener:20261016:v1:retry1'})));
 assert.ok(plan(existing(),incoming({requestId:undefined})));
});
test('malformed dates and publication timestamps fail closed',()=>{
 for(const marketDate of ['2026-02-30','2026-13-01','2026-1-01','garbage',null]) {
  assert.equal(plan(existing({marketDate}),incoming({marketDate})),null);
 }
 for(const publicationGeneratedAt of [null,generated,'2026-10-16','garbage',
  '2026-02-30T10:00:00Z','2026-10-16T25:00:00Z','2026-10-16T10:61:00Z']) {
  assert.equal(plan(existing({publicationGeneratedAt})),null);
 }
 assert.ok(plan(existing({publicationGeneratedAt:'2026-10-16T18:00:00+08:00'})));
 for(const now of [undefined,null,'2026-10-16',NaN,Infinity]) {
  assert.equal(planFreshnessRecovery(existing(),incoming(),now),null);
 }
});
test('malformed gaps or request lineage never become guessed revision plans',()=>{
 for(const publicationFreshnessGaps of [undefined,null,[],{},
  {price:['2330'],regression:[]},{price:'2330',regression:[],institution:[]},
  {price:[2330],regression:[],institution:[]},{price:[''],regression:[],institution:[]},
  {price:['2330'],regression:[null],institution:[]}]) {
  assert.equal(plan(existing({publicationFreshnessGaps})),null);
 }
 for(const requestId of [null,undefined,'invalid id','x'.repeat(161)]) {
  assert.equal(plan(existing({requestId})),null);
 }
 for(const state of [null,undefined,[],true])assert.equal(planFreshnessRecovery(state,incoming(),generated+1800000),null);
 for(const input of [null,undefined,[],true])assert.equal(planFreshnessRecovery(existing(),input,generated+1800000),null);
});
test('auxiliary warnings and provider budget do not alter eligibility or get copied into revision metadata',()=>{
 const result=plan(existing({notionStatus:'failed',cacheStatus:'pending_recovery',
  errorCategory:'notion_http_503',budget:{used:300},finmindToken:'not-a-real-token'}));
 assert.equal(result.requestId,'stockscreener:20261016:refresh1');
 assert.deepEqual(Object.keys(result).sort(),['freshnessRefreshCount','mode','previousPublishedRequestId','requestId']);
});

test('publication evidence includes unselected stock warnings across the full exported roster',()=>{
 assert.equal(typeof publicationFreshnessEvidence,'function');
 const payload={freshness:'degraded',generatedAt:'2026-10-16T10:00:00.000Z',
  selectedStocks:[{code:'2330'}],dataQuality:{warnings:[
   {code:'price_date',stockCode:'6173'}, {code:'regression_date',stockCode:'6173'},
   {code:'institution_date',stockCode:'2330'},
   {code:'institution_window_incomplete',stockCode:'6173'},
   {code:'institution_date',stockCode:'6173'},
  ]}};
 const before=JSON.stringify(payload);
 const evidence=publicationFreshnessEvidence(payload);
 assert.deepEqual(evidence,{publicationFreshness:'degraded',publicationGeneratedAt:payload.generatedAt,
  publicationFreshnessGaps:{price:['6173'],regression:['6173'],institution:['2330','6173']}});
 assert.equal(JSON.stringify(payload),before);
 assert.ok(plan(existing(evidence)));
});
test('unrecognized financial warnings and malformed warning entries never create reacquisition work',()=>{
 for(const warnings of [undefined,null,{},[],[
  null,{},'price_date:6173', {code:'financial_missing',stockCode:'6173'},
  {code:'price_date'}, {code:'price_date',stockCode:6173},
  {code:'price_date',stockCode:'bad'}, {code:'price_date',stockCode:'../6173'},
 ]]) {
  const evidence=publicationFreshnessEvidence({freshness:'degraded',generatedAt:'2026-10-16T10:00:00Z',dataQuality:{warnings}});
  assert.deepEqual(evidence.publicationFreshnessGaps,{price:[],regression:[],institution:[]});
  assert.equal(plan(existing(evidence)),null);
 }
});
test('missing publication evidence fails closed without guessing',()=>{
 for(const payload of [null,undefined,[],{},true]) {
  const evidence=publicationFreshnessEvidence(payload);
  assert.deepEqual(evidence,{publicationFreshness:'unknown',publicationGeneratedAt:null,
   publicationFreshnessGaps:{price:[],regression:[],institution:[]}});
  assert.equal(plan(existing(evidence)),null);
 }
});
