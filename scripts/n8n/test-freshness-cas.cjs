const test=require('node:test'),assert=require('node:assert/strict'),engine=require('./engine.cjs'),outcome=require('./outcome.cjs');
const generated='2026-10-16T10:00:00Z',now=Date.parse(generated)+30*60000;
const incoming={marketDate:'2026-10-16',requestId:'stockscreener:20261016:v1',owner:'new',mode:'screen',runKind:'scheduled',automaticRequestId:true,siteUrl:'https://stockscreener.andyshih.uk'};
const gaps={price:['6173'],regression:['6173'],institution:['6173']};
const old={...incoming,owner:'old',released:true,screeningStatus:'complete',publicationStatus:'verified',deployStatus:'verified',notionStatus:'complete',cacheStatus:'not_generated',publicationFreshness:'degraded',publicationGeneratedAt:generated,publicationFreshnessGaps:gaps,actionsRunId:'123',runHeadSha:'a'.repeat(40),freshnessRefreshCount:0};
const response=(body,statusCode=200)=>({body,statusCode});
const read=(existing=old,changes={},time=now)=>engine.advance({...engine.start({...incoming,...changes},time).state,stage:'state',isOpen:true},response({sha:'old-sha',content:Buffer.from(JSON.stringify(existing)).toString('base64')}),time);
test('degraded 6173 release is claimed with exact CAS before fresh acquisition',()=>{
 const out=read();assert.equal(out.state.requestId,'stockscreener:20261016:refresh1');assert.equal(out.state.mode,'revision');assert.equal(out.state.freshnessRefreshCount,1);assert.equal(out.state.nextStage,'findRun');assert.equal(out.state.actionsRunId,undefined);assert.equal(out.state.deployStatus,'pending');assert.equal(out.op.method,'PUT');assert.equal(out.op.body.sha,'old-sha');
 const saved=JSON.parse(Buffer.from(out.op.body.content,'base64').toString());assert.equal(saved.previousPublishedRequestId,old.requestId);assert.equal(saved.actionsRunId,undefined);
 const conflict=engine.advance(out.state,response({},409),now);assert.equal(conflict.state.errorCategory,'writer_conflict');assert.equal(conflict.op,null);
 const claimed=engine.advance(out.state,response({content:{sha:'new-sha'}}),now);assert.equal(claimed.state.stage,'findRun');assert.equal(claimed.op.method,'GET');assert.ok(claimed.op.url.includes('/actions/workflows/daily.yml/runs'));
});
test('active writer and already dispatched revision never create a duplicate producer',()=>{
 const active=read({...old,released:false,deadline:now+60000});assert.equal(active.state.waitingForOwner,'old');assert.equal(active.op.method,'GET');
 const revision={...old,requestId:'stockscreener:20261016:refresh1',screeningStatus:'pending',publicationStatus:'pending',deployStatus:'pending',freshnessRefreshCount:1};
 const resumed=read(revision);assert.equal(resumed.state.requestId,revision.requestId);assert.equal(resumed.state.nextStage,'pollRun');assert.equal(resumed.state.actionsRunId,'123');assert.equal(resumed.state.freshnessRefreshCount,1);
});
test('refresh interval and six-run ceiling leave existing producer unchanged',()=>{
 for(const [stored,time] of [[old,now-1],[{...old,freshnessRefreshCount:6},now]]){const out=read(stored,{},time);assert.equal(out.state.screeningStatus,'already_complete');assert.equal(out.state.requestId,stored.requestId);assert.equal(out.op,null);}
});
test('explicit manual resume keeps original request and provider budget input',()=>{
 const out=read(old,{runKind:'manual',mode:'resume',automaticRequestId:false,budget:{used:300,limit:300}});assert.equal(out.state.requestId,old.requestId);assert.equal(out.state.freshnessRefreshCount,0);
 const automatic=read(old,{budget:{used:300,limit:300}});assert.deepEqual(automatic.state.budget,{used:300,limit:300});assert.equal(automatic.state.freshnessRefreshCount,1);
});
test('publicationMain persists full-roster 6173 evidence into durable checkpoint',()=>{
 const payload={freshness:'degraded',generatedAt:generated,selectedStocks:[{code:'2330'}],dataQuality:{warnings:[{code:'price_date',stockCode:'6173'},{code:'regression_date',stockCode:'6173'},{code:'institution_window_incomplete',stockCode:'6173'}]}};
 const input={...engine.start(incoming,now).state,stage:'publicationMain',payload,publication:{publishedGitCommit:'a'.repeat(40)},deployStatus:'verified'};
 const out=engine.advance(input,response({status:'identical',base_commit:{sha:'a'.repeat(40)}}),now);
 assert.equal(out.state.nextStage,'liveVerify');const saved=JSON.parse(Buffer.from(out.op.body.content,'base64').toString());assert.equal(saved.publicationFreshness,'degraded');assert.equal(saved.publicationGeneratedAt,generated);assert.deepEqual(saved.publicationFreshnessGaps,gaps);assert.equal(saved.payload,undefined);
});
test('verified degraded publication remains warning even when auxiliary tasks complete',()=>{
 const state={...old,stage:'done',cacheStatus:'verified'};const result=outcome.operationOutcome(state);assert.equal(result.outcome,'published_with_warnings');assert.equal(result.publicationFreshness,'degraded');assert.deepEqual(result.publicationFreshnessGaps,gaps);assert.equal(result.freshnessRefreshCount,0);assert.equal(result.nextFreshnessRefreshAfter,'2026-10-16T10:30:00.000Z');
 assert.equal(outcome.operationOutcome({...state,freshnessRefreshCount:6}).nextFreshnessRefreshAfter,null);
 assert.equal(outcome.operationOutcome({...state,publicationFreshness:'current'}).nextFreshnessRefreshAfter,null);
 assert.equal(outcome.operationOutcome({...state,deployStatus:'failed'}).outcome,'failed');
});
test('failed refresh producer preserves the daily refresh ceiling across automatic retries',()=>{
 const failed={...old,requestId:'stockscreener:20261016:refresh6',freshnessRefreshCount:6,screeningStatus:'failed',publicationStatus:'pending',deployStatus:'pending',automaticRetryCount:1};
 const retried=read(failed);
 assert.equal(retried.state.freshnessRefreshCount,6);
 assert.equal(JSON.parse(Buffer.from(retried.op.body.content,'base64').toString()).freshnessRefreshCount,6);
});
