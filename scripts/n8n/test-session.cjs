const test=require('node:test');const assert=require('node:assert/strict');
const engine=require('./engine.cjs');
const calendar=[{Name:'國曆新年開始交易日',Date:'1150102'},{Name:'國慶日',Date:'1151009'},{Name:'中秋節',Date:'1150925'}];
const base={marketDate:'2026-10-03',requestId:'stockscreener:20261003:v1',mode:'screen',runKind:'manual',resolveLatest:true,automaticRequestId:true,siteUrl:'https://stockscreener.andyshih.uk',owner:'operator'};
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
 const prior={marketDate:'2026-10-02',requestId:'stockscreener:20261002:v2',owner:'previous',mode:'revision',released:true,deadline:now-120000,actionsRunId:'456',dispatchIntent:true,screeningStatus:'complete',notionStatus:'complete',deployStatus:'verified',payloadHash:'a'.repeat(64)};
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
