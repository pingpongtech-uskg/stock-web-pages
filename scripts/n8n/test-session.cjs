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
