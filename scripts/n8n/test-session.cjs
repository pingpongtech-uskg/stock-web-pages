const test=require('node:test');const assert=require('node:assert/strict');
const engine=require('./engine.cjs');
const calendar=[{Name:'國曆新年開始交易日',Date:'1150102'},{Name:'國慶日',Date:'1151009'},{Name:'中秋節',Date:'1150925'}];
const base={marketDate:'2026-10-03',requestId:'stockscreener:20261003:v1',mode:'screen',runKind:'manual',resolveLatest:true,automaticRequestId:true,siteUrl:'https://stockscreener.andyshih.uk',owner:'operator'};
function finishCheckpoint(out,now) {return out.state.stage==='checkpoint'?engine.advance(out.state,{statusCode:200,body:{content:{sha:'checkpoint-sha'}}},now):out;}
test('normal manual resolves Saturday to official Friday session without using website freshness',()=>{
 const now=Date.parse('2026-10-02T22:26:00Z');const out=engine.advance(engine.start(base,now).state,{statusCode:200,body:calendar},now);
 assert.equal(out.state.marketDate,'2026-10-02');assert.equal(out.state.requestId,'stockscreener:20261002:v1');assert.equal(out.state.isOpen,true);assert.equal(out.state.requestedAtDate,'2026-10-03');
});
test('completed-session resolution handles preclose, holiday weekend and rejects unavailable year',()=>{
 assert.equal(typeof engine.latestCompletedSession,'function');
 assert.equal(engine.latestCompletedSession(calendar,Date.parse('2026-10-02T05:29:59Z')),'2026-10-01');
 assert.equal(engine.latestCompletedSession(calendar,Date.parse('2026-10-02T05:30:00Z')),'2026-10-02');
 assert.equal(engine.latestCompletedSession(calendar,Date.parse('2026-10-10T01:00:00Z')),'2026-10-08');
 assert.throws(()=>engine.latestCompletedSession(calendar,Date.parse('2027-01-01T01:00:00Z')),/calendar_year/);
 assert.throws(()=>engine.latestCompletedSession([{Name:'開國紀念日',Date:'1160101'}],Date.parse('2027-01-01T06:00:00Z')),/calendar_year_boundary/);
 assert.throws(()=>engine.latestCompletedSession([],Date.parse('2026-10-03T01:00:00Z')),/calendar_empty/);
});
test('normal manual recovery resumes prior exact run after original cutoff with audited new window',()=>{
 const now=Date.parse('2026-10-03T01:00:00Z');const initial=engine.start(base,now).state;
 const prior={marketDate:'2026-10-02',requestId:'stockscreener:20261002:v1',owner:'previous',released:false,deadline:now-120000,operationDeadline:now-3600000,overdueAt:Date.parse('2026-10-02T11:30:00Z'),actionsRunId:'123',dispatchIntent:true};
 const state={...initial,stage:'state',marketDate:prior.marketDate,requestId:prior.requestId,isOpen:true};
 const out=engine.advance(state,{statusCode:200,body:{sha:'observed',content:Buffer.from(JSON.stringify(prior)).toString('base64')}},now);
 assert.equal(out.state.nextStage,'pollRun');assert.equal(out.state.actionsRunId,'123');assert.equal(out.state.manualDeadlineOverride,true);assert.equal(out.state.operationDeadline,now+90*60000);assert.equal(out.op.url.includes('dispatches'),false);
 const busy=engine.advance(state,{statusCode:200,body:{sha:'observed',content:Buffer.from(JSON.stringify({...prior,deadline:now+1000})).toString('base64')}},now);
 assert.equal(busy.state.errorCategory,'writer_busy');assert.equal(busy.op,null);
});
test('explicit diagnostics keep requested date and clearly separate diagnostic status from screening',()=>{
 const now=Date.parse('2026-10-03T01:00:00Z');const out=engine.advance(engine.start({...base,mode:'diagnose'},now).state,{statusCode:200,body:calendar},now);
 assert.equal(out.state.marketDate,'2026-10-03');assert.equal(out.state.stage,'diagnoseDatabase');assert.equal(out.state.isOpen,false);
});
test('explicit confirmed-preflight correction requires exact released failed owner and still searches before dispatch',()=>{
 const now=Date.parse('2026-10-03T01:00:00Z');const initial=engine.start({...base,preflightRetryOwner:'819'},now).state;
 const prior={marketDate:'2026-10-02',requestId:'stockscreener:20261002:v1',owner:'819',released:true,deadline:now-120000,dispatchIntent:true,errorCategory:'dispatch_run_not_found',errorMessage:'prior unknown response',screeningStatus:'pending'};
 const state={...initial,stage:'state',marketDate:prior.marketDate,requestId:prior.requestId,isOpen:true};
 const read=value=>({statusCode:200,body:{sha:'observed',content:Buffer.from(JSON.stringify(value)).toString('base64')}});
 const out=engine.advance(state,read(prior),now);
 assert.equal(out.state.dispatchIntent,false);assert.equal(out.state.confirmedPreflightCorrectionFrom,'819');assert.equal(out.state.preflightRetryOwner,undefined);assert.equal(out.state.errorCategory,'');assert.equal(out.state.nextStage,'findRun');
 const claim=engine.advance(out.state,{statusCode:200,body:{content:{sha:'claimed'}}},now);assert.equal(claim.op.method,'GET');assert.ok(claim.op.url.includes('/actions/workflows/daily.yml/runs'));
 const matched=engine.advance(claim.state,{statusCode:200,body:{workflow_runs:[{id:123,display_title:'Daily screening | stockscreener:20261002:v1 | 2026-10-02'}]}},now);assert.equal(matched.state.nextStage,'pollRun');assert.equal(matched.state.actionsRunId,'123');
 for(const invalid of [{...prior,owner:'other'},{...prior,released:false},{...prior,actionsRunId:'123'},{...prior,errorCategory:'external_http_403'},{...prior,requestId:'different'},{...prior,marketDate:'2026-10-01'}])assert.equal(engine.advance(state,read(invalid),now).state.errorCategory,'preflight_correction_scope');
 assert.throws(()=>engine.start({...base,preflightRetryOwner:'../819'},now),/invalid_preflight_retry_owner/);
 assert.throws(()=>engine.start({...base,preflightRetryOwner:'819',runKind:'scheduled'},now),/invalid_preflight_retry_owner/);
});
test('normal automatic manual adopts same-day corrected request for exact resume and identical retry',()=>{
 const now=Date.parse('2026-10-03T01:00:00Z');const initial=engine.start(base,now).state;
 const prior={marketDate:'2026-10-02',requestId:'stockscreener:20261002:v2',owner:'previous',mode:'revision',released:true,deadline:now-120000,actionsRunId:'456',dispatchIntent:true,cacheStatus:'verified',screeningStatus:'complete',notionStatus:'complete',deployStatus:'verified',payloadHash:'a'.repeat(64)};
 const state={...initial,stage:'state',marketDate:prior.marketDate,requestId:'stockscreener:20261002:v1',isOpen:true};const read=value=>({statusCode:200,body:{sha:'observed',content:Buffer.from(JSON.stringify(value)).toString('base64')}});
 const complete=engine.advance(state,read(prior),now);assert.equal(complete.state.requestId,prior.requestId);assert.equal(complete.state.actionsRunId,'456');assert.equal(complete.state.screeningStatus,'already_complete');assert.equal(complete.op,null);
 const resume=engine.advance(state,read({...prior,screeningStatus:'pending',notionStatus:'pending',deployStatus:'pending'}),now);assert.equal(resume.state.nextStage,'pollRun');assert.equal(resume.state.actionsRunId,'456');assert.equal(resume.state.requestId,prior.requestId);assert.equal(resume.state.automaticRequestAdoptedFrom,'stockscreener:20261002:v1');
 const explicit=engine.advance({...state,automaticRequestId:false},read(prior),now);assert.equal(explicit.state.errorCategory,'request_correction_requires_revision');
 const otherDate=engine.advance(state,read({...prior,marketDate:'2026-10-01'}),now);assert.equal(otherDate.state.errorCategory,'request_correction_requires_revision');
 const legacy=engine.advance(state,read({...prior,archiveMethod:'legacy_archive'}),now);assert.equal(legacy.state.errorCategory,'request_correction_requires_revision');
 const pendingIntent=engine.advance(state,read({...prior,actionsRunId:'',screeningStatus:'pending',notionStatus:'pending',deployStatus:'pending'}),now);assert.equal(pendingIntent.state.nextStage,'findRun');assert.equal(pendingIntent.state.dispatchIntent,true);
 const busy=engine.advance(state,read({...prior,released:false,deadline:now+1000}),now);assert.equal(busy.state.errorCategory,'writer_busy');assert.equal(busy.state.requestId,'stockscreener:20261002:v1');assert.equal(busy.op,null);
 for(const invalid of [{...prior,requestId:'../../bad'},{...prior,actionsRunId:'../456'}])assert.equal(engine.advance(state,read(invalid),now).state.errorCategory,'invalid_stored_request_lineage');
});
test('scheduled source-step failure gets one metadata-verified retry with a new request id',()=>{
 const now=Date.parse('2026-10-02T10:30:00Z');
 const state={...engine.start({...base,marketDate:'2026-10-02',resolveLatest:false,runKind:'scheduled',requestId:'stockscreener:20261002:v1'},now).state,stage:'pollRun',lockSha:'state-sha',actionsRunId:'123',released:false};
 const failedRun={id:123,display_title:'Daily screening | stockscreener:20261002:v1 | 2026-10-02',path:'.github/workflows/daily.yml@refs/heads/main',event:'workflow_dispatch',head_branch:'main',head_sha:'a'.repeat(40),run_attempt:1,status:'completed',conclusion:'failure'};
 const jobs=finishCheckpoint(engine.advance(state,{statusCode:200,body:failedRun},now),now);
 assert.equal(jobs.state.stage,'failedRunJobs');assert.equal(jobs.op.url,'https://api.github.com/repos/pingpongtech-uskg/stock-web-pages/actions/runs/123/jobs?per_page=100');
 const steps=[
  {name:'Fetch authoritative exchange calendar',status:'completed',conclusion:'success'},
  {name:'Fetch official institutional universe',status:'completed',conclusion:'failure'},
  {name:'Verify independent requested date against fetched official date',status:'completed',conclusion:'skipped'},
  {name:'Publish validated release to main',status:'completed',conclusion:'skipped'},
 ];
 const jobMetadata={run_id:'123',run_attempt:1,head_sha:'a'.repeat(40)};
 const jobPayload=steps=>({total_count:2,jobs:[{...jobMetadata,name:'snapshot',status:'completed',conclusion:'failure',steps},{...jobMetadata,name:'institutional_probe',status:'completed',conclusion:'skipped',steps:[]}]});
 const artifacts=finishCheckpoint(engine.advance(jobs.state,{statusCode:200,body:jobPayload(steps)},now),now);
 assert.equal(artifacts.state.stage,'failedRunArtifacts');assert.ok(artifacts.op.url.endsWith('/actions/runs/123/artifacts?per_page=100'));
 const receiptLineage={id:123,repository_id:1273106108,head_repository_id:1273106108,head_sha:'a'.repeat(40),event:'workflow_dispatch',head_branch:'main'};
 const retryCheckpoint=engine.advance(artifacts.state,{statusCode:200,body:{total_count:2,artifacts:[{id:501,name:'market-source-checkpoint-1',expired:false,workflow_run:receiptLineage},{id:502,name:'finmind-checkpoint-1',expired:false,workflow_run:receiptLineage}]}},now);
 const retry=finishCheckpoint(retryCheckpoint,now);
 assert.equal(retry.state.automaticRetryCount,1);assert.equal(retry.state.automaticRetry.originalActionsRunId,'123');
 assert.equal(retry.state.automaticRetry.failedStep,'Fetch official institutional universe');
 assert.equal(retry.state.requestId,'stockscreener:20261002:v1:retry1');
 assert.equal(retry.state.actionsRunId,undefined);assert.equal(retry.state.dispatchIntent,false);
 assert.equal(retry.state.stage,'findRun');assert.ok(retryCheckpoint.op.body.message.startsWith('[CF-Pages-Skip] '));
 assert.equal(retry.op.method,'GET');assert.ok(retry.op.url.includes('/actions/workflows/daily.yml/runs'));
});
test('automatic source retry fails closed for nonallowlisted jobs, artifacts, manual runs and a second failure',()=>{
 const now=Date.parse('2026-10-02T10:30:00Z');
 const initial={...engine.start({...base,runKind:'scheduled'},now).state,stage:'pollRun',lockSha:'sha',actionsRunId:'123'};
 const run={id:123,display_title:'Daily screening | stockscreener:20261003:v1 | 2026-10-03',path:'.github/workflows/daily.yml@refs/heads/main',event:'workflow_dispatch',head_branch:'main',head_sha:'a'.repeat(40),run_attempt:1,status:'completed',conclusion:'failure'};
 const failed=finishCheckpoint(engine.advance(initial,{statusCode:200,body:run},now),now);
 const jobMetadata={run_id:'123',run_attempt:1,head_sha:'a'.repeat(40)};
 const reject=steps=>finishCheckpoint(engine.advance(failed.state,{statusCode:200,body:{total_count:2,jobs:[{...jobMetadata,name:'snapshot',status:'completed',conclusion:'failure',steps},{...jobMetadata,name:'institutional_probe',status:'completed',conclusion:'skipped',steps:[]}] }},now),now);
 const nonSource=reject([{name:'Fetch ownership reference cache',status:'completed',conclusion:'failure'}]);
 assert.equal(nonSource.state.stage,'rootSchema');assert.equal(nonSource.state.recordFailure,true);
 const malformed=reject([{name:'Fetch official institutional universe',status:'completed',conclusion:'failure'},{name:'npm run build',status:'completed',conclusion:'failure'}]);
 assert.equal(malformed.state.stage,'rootSchema');
 const wrongLineage=engine.advance(failed.state,{statusCode:200,body:{total_count:2,jobs:[{...jobMetadata,run_attempt:2,name:'snapshot',status:'completed',conclusion:'failure',steps:[{name:'Fetch official institutional universe',status:'completed',conclusion:'failure'}]},{...jobMetadata,name:'institutional_probe',status:'completed',conclusion:'skipped',steps:[]}]}},now);
 assert.equal(finishCheckpoint(wrongLineage,now).state.stage,'rootSchema');
 const source=reject([{name:'Fetch official institutional universe',status:'completed',conclusion:'failure'}]);
 const receiptLineage={id:123,repository_id:1273106108,head_repository_id:1273106108,head_sha:'a'.repeat(40),event:'workflow_dispatch',head_branch:'main'};
 const artifact=finishCheckpoint(engine.advance(source.state,{statusCode:200,body:{total_count:1,artifacts:[{id:501,name:'screening-export',expired:true,workflow_run:receiptLineage}]}},now),now);
 assert.equal(artifact.state.stage,'rootSchema');assert.equal(artifact.state.recordFailure,true);
 for(const malformed of [null,{}, {name:'unknown-checkpoint-1',id:503,expired:false,workflow_run:receiptLineage}, {id:504,name:'finmind-checkpoint-1',expired:false,workflow_run:{...receiptLineage,id:999}}]) {
  const rejected=finishCheckpoint(engine.advance(source.state,{statusCode:200,body:{total_count:1,artifacts:[malformed]}},now),now);
  assert.equal(rejected.state.stage,'rootSchema');
 }
 const manual={...initial,runKind:'manual'};
 assert.equal(finishCheckpoint(engine.advance(manual,{statusCode:200,body:run},now),now).state.stage,'rootSchema');
 const second={...initial,automaticRetryCount:1};
 assert.equal(finishCheckpoint(engine.advance(second,{statusCode:200,body:run},now),now).state.stage,'rootSchema');
});
test('retry run lookup gets its own bounded dispatch window after a slow original run',()=>{
 const now=Date.parse('2026-10-02T10:30:00Z');
 const state={...engine.start({...base,runKind:'scheduled'},now).state,stage:'findRun',startedAt:now-10*60000,requestId:'stockscreener:20261003:v1:retry1',automaticRetryCount:1,dispatchIntent:true,dispatchStartedAt:now};
 const lookup=engine.advance(state,{statusCode:200,body:{workflow_runs:[]}},now+1000);
 assert.equal(lookup.state.stage,'findRun');assert.equal(lookup.state.errorCategory,undefined);assert.equal(lookup.delaySeconds,15);
 const expired=engine.advance(state,{statusCode:200,body:{workflow_runs:[]}},now+5*60000+1);
 assert.equal(expired.state.errorCategory,'dispatch_run_not_found');
});
test('dispatch intent timestamp survives its CAS commit and state rehydration before first empty search',()=>{
 const oldStart=Date.parse('2026-10-02T10:00:00Z');const dispatchAt=oldStart+10*60000;const resumeAt=oldStart+11*60000;
 const initial={...engine.start({...base,runKind:'scheduled'},oldStart).state,stage:'findRun',startedAt:oldStart,lockSha:'before',isOpen:true};
 const preparing=engine.advance(initial,{statusCode:200,body:{workflow_runs:[]}},dispatchAt);
 assert.equal(preparing.state.stage,'checkpoint');assert.equal(preparing.state.nextStage,'dispatch');
 const casState=JSON.parse(Buffer.from(preparing.op.body.content,'base64').toString('utf8'));
 assert.equal(casState.dispatchStartedAt,dispatchAt);assert.equal(casState.stage,'dispatch');
 const recovering={...engine.start({...base,runKind:'scheduled',owner:'recovery'},resumeAt).state,stage:'state',isOpen:true};
 const resumed=engine.advance(recovering,{statusCode:200,body:{sha:'state-sha',content:Buffer.from(JSON.stringify({...casState,owner:'old',deadline:resumeAt-120000})).toString('base64')}},resumeAt);
 const search=finishCheckpoint(resumed,resumeAt);
 assert.equal(search.state.dispatchStartedAt,dispatchAt);assert.equal(search.state.stage,'findRun');
 const firstEmpty=engine.advance(search.state,{statusCode:200,body:{workflow_runs:[]}},resumeAt+1000);
 assert.equal(firstEmpty.state.stage,'findRun');assert.notEqual(firstEmpty.state.errorCategory,'dispatch_run_not_found');
});
