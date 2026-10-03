const {growthFixture}=require('./growth-fixture.cjs');
const test=require('node:test'); const assert=require('node:assert/strict');
let engine={}; try {engine=require('./engine.cjs');} catch(error){if(error.code!=='MODULE_NOT_FOUND') throw error;}
const now=Date.parse('2026-10-02T10:00:00Z');
const input={marketDate:'2026-10-02',requestId:'test-1',mode:'screen',siteUrl:'https://stockscreener.andyshih.uk',owner:'700'};
const response=(body,statusCode=200,headers={})=>({body,statusCode,headers});
test('independent calendar begins before any dispatch or mutation',()=>{
  assert.equal(typeof engine.start,'function');const out=engine.start(input,now);
  assert.equal(out.op.url,'https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule');
  assert.equal(out.op.method,'GET');
});
test('HTTP Request text response data field normalizes to calendar body',()=>{
  const output=engine.start({...input,mode:'diagnose'},now);
  const next=engine.advance(output.state,{statusCode:200,data:'[{"Name":"國曆新年開始交易日","Date":"1150102"}]'},now);
  assert.equal(next.state.stage,'diagnoseDatabase');
});
test('calendar closures distinct from explicit opening days; stale calendar fails closed',()=>{
  assert.equal(typeof engine.calendarOpen,'function');const calendar=[{Name:'開始交易日',Date:'1150102'},{Name:'國慶日',Date:'1151009'}];
  assert.equal(engine.calendarOpen(calendar,'2026-01-02'),true);
  assert.equal(engine.calendarOpen(calendar,'2026-10-09'),false);
  assert.throws(()=>engine.calendarOpen(calendar,'2027-10-01'),/calendar_year/);
  assert.throws(()=>engine.calendarOpen([],'2026-10-02'),/calendar_empty/);
  assert.equal(engine.calendarOpen([{Name:'國曆新年開始交易日',Date:'1150102'}],'2026-01-02'),true);
  assert.equal(engine.calendarOpen([{Name:'農曆春節前最後交易日',Date:'1150211'}],'2026-02-11'),true);
  assert.equal(engine.calendarOpen([{Name:'農曆春節後開始交易日',Date:'1150223'}],'2026-02-23'),true);
});
test('atomic state claims reference exact blob sha and refuse active owner',()=>{
  assert.equal(typeof engine.advance,'function');
  let out=engine.start(input,now);out=engine.advance(out.state,response([{Name:'開始交易日',Date:'1150102'}]),now);
  assert.ok(out.op.url.includes('/git/ref/heads/n8n-state'));
  out=engine.advance(out.state,response({object:{sha:'a'.repeat(40)}}),now);
  out=engine.advance(out.state,response({sha:'blob',content:Buffer.from(JSON.stringify({owner:'other',released:false,deadline:now+100000})).toString('base64')}),now);
  assert.equal(out.route,'done');assert.equal(out.state.errorCategory,'writer_busy');
});
test('ambiguous dispatch resumes exact request run search, never dispatches twice',()=>{
  assert.equal(typeof engine.advance,'function');
  const out=engine.advance({...input,stage:'dispatch',deadline:now+100000,lockSha:'blob'},response({},503),now);
  assert.equal(out.op.method,'GET');assert.ok(out.op.url.includes('/actions/workflows/daily.yml/runs'));
});
test('confirmed native dispatch preflight failure releases its intent without claiming an API attempt',()=>{
 const out=engine.advance({...input,stage:'dispatch',dispatchIntent:true,deadline:now+100000,lockSha:'blob'}, {statusCode:400,preflightFailed:true,body:{message:'Inputs: Invalid JSON'}},now);
 assert.equal(out.state.errorCategory,'dispatch_preflight_failed');assert.equal(out.state.errorMessage,'Inputs: Invalid JSON');
 assert.equal(out.state.dispatchIntent,false);assert.equal(out.state.released,true);assert.equal(out.state.screeningStatus,'failed');
 assert.equal(out.state.nextStage,'done');assert.equal(out.op.method,'PUT');
});
test('Notion 429 waits advertised duration; ambiguous create returns to read',()=>{
  assert.equal(typeof engine.advance,'function');
  const state={...input,stage:'createDaily',deadline:now+100000,lockSha:'blob',op:{target:'notion',method:'POST',url:'https://api.notion.com/v1/pages',body:{}},retry:0};
  const out=engine.advance(state,response({},429,{'retry-after':'10'}),now);
  assert.equal(out.delaySeconds,10);assert.equal(out.op.method,'POST');
  const ambiguous=engine.advance(state,response({},503),now);
  assert.equal(ambiguous.state.stage,'findDaily');assert.ok(ambiguous.op.url.endsWith('/query'));
});
test('Actions correlation matches exact run title and rejects multiple matches',()=>{
  assert.equal(typeof engine.selectRun,'function');
  assert.equal(engine.selectRun([{id:1,display_title:'Daily screening | test-1 | 2026-10-02'},{id:2,display_title:'Daily screening | unrelated | 2026-10-02'}],input).id,1);
  assert.throws(()=>engine.selectRun([{id:1,display_title:'Daily screening | test-1 | 2026-10-02'},{id:2,display_title:'Daily screening | test-1 | 2026-10-02'}],input),/ambiguous_actions/);
});
test('lease expiry prevents any further external write',()=>{
  assert.equal(typeof engine.advance,'function');
  const out=engine.advance({...input,stage:'createDaily',deadline:now-1,lockSha:'blob'},response({},200),now);
  assert.equal(out.route,'done');assert.equal(out.state.errorCategory,'writer_deadline');
});
test('deployment mismatch polls within bounded lease instead of declaring immediate failure',()=>{
  assert.equal(typeof engine.advance,'function');
  const state={...input,stage:'liveVerify',deadline:now+100000,lockSha:'blob',payload:{payloadHash:'a'.repeat(64)}};
  const out=engine.advance(state,response('{}'),now);
  assert.equal(out.state.stage,'liveVerify');assert.equal(out.delaySeconds,15);
});
test('checkpoint conflict aborts writer and malformed schemas fail closed',()=>{
  const conflicted=engine.advance({...input,stage:'checkpoint',deadline:now+100000,lockSha:'old'},response({},409),now);
  assert.equal(conflicted.route,'done');assert.equal(conflicted.state.errorCategory,'writer_conflict');
  const malformed=engine.advance(engine.start(input,now).state,response([{Name:'bad',Date:'garbage'}]),now);
  assert.equal(malformed.state.errorCategory,'calendar_schema');
});
test('read requests use bounded retries and rate limiting exhaustion persists failure',()=>{
  const state={...input,stage:'rootSchema',deadline:now+100000,lockSha:'blob',op:{target:'notion',method:'GET',url:'https://api.notion.com/v1/data_sources/root',body:{}}};
  const retry=engine.advance(state,response({},503),now);assert.equal(retry.delaySeconds,2);assert.equal(retry.state.retry,1);
  const exhausted=engine.advance({...state,retry:8},response({},429),now);assert.equal(exhausted.state.errorCategory,'rate_limit_exhausted');assert.equal(exhausted.state.notionStatus,'failed');
  const checkpointFailure=engine.advance({...state,stage:'checkpoint'},response({},503),now);assert.equal(checkpointFailure.route,'done');assert.equal(checkpointFailure.state.errorCategory,'checkpoint_failed');
});
test('live 404 preserves archive and retries; terminal deploy failure still finalizes Notion',()=>{
  const state={...input,stage:'liveVerify',deadline:now+100000,lockSha:'blob',payload:{runId:'run',sourceGitCommit:'a'.repeat(40),generatedAt:'2026-10-02T10:00:00Z',freshness:'current',revision:'b'.repeat(12),payloadHash:'c'.repeat(64),selectedStocks:[],strategies:{trust:[],growth:[],lowPosition:[]},coverage:{},formulaVersions:{}},pageId:'page',actionsRunId:'123'};
  assert.equal(engine.advance(state,response({},404),now).state.stage,'liveVerify');
  const terminal=engine.advance({...state,deployAttempts:20},response({},404),now);assert.equal(terminal.state.stage,'finishNotion');assert.equal(terminal.state.deployStatus,'failed');assert.equal(terminal.op.body.properties['Notion Status'].rich_text[0].text.content,'complete');
});
test('late Actions same-day recovery retains exact run and absolute 19:30 cutoff',()=>{
  const start18=Date.parse('2026-10-02T10:00:00Z');const retry1910=Date.parse('2026-10-02T11:10:00Z');
  const original=engine.start({...input,runKind:'scheduled'},start18).state;
  const previous={...original,stage:'pollRun',actionsRunId:'123',owner:'original',lockSha:'old',released:false};
  const expired=engine.advance(previous,response({status:'completed'}),Date.parse('2026-10-02T11:05:00Z'));
  assert.equal(expired.state.errorCategory,'writer_deadline');
  let recovery=engine.start({...input,runKind:'scheduled',owner:'recovery'},retry1910);
  recovery=engine.advance(recovery.state,response([{Name:'國曆新年開始交易日',Date:'1150102'}]),retry1910);
  recovery=engine.advance(recovery.state,response({object:{sha:'main'}}),retry1910);
  recovery=engine.advance(recovery.state,response({sha:'old',content:Buffer.from(JSON.stringify(previous)).toString('base64')}),retry1910);
  assert.equal(recovery.state.nextStage,'pollRun');assert.equal(recovery.state.actionsRunId,'123');
  assert.equal(recovery.state.deadline,Date.parse('2026-10-02T11:30:00Z'));
  assert.equal(recovery.op.url.includes('/dispatches'),false);
});
test('operator Actions IDs are decimal; checkpoint commits skip Cloudflare preview builds',()=>{
  assert.throws(()=>engine.start({...input,actionsRunId:'123/../../issues'},now),/invalid_actions_run_id/);
  const state={...engine.start(input,now).state,stage:'state',isOpen:true};
  const claim=engine.advance(state,response({},404),now);
  assert.ok(claim.op.body.message.startsWith('[CF-Pages-Skip] '));
  assert.equal(engine.start({...input,actionsRunId:'123'},now).state.actionsRunId,'123');
  assert.throws(()=>engine.start({...input,siteUrl:'https://localhost'},now),/invalid_site_url/);
});
test('manual resume after cutoff has an explicit new window but cannot steal a live lease',()=>{
  const manualNow=Date.parse('2026-10-02T13:00:00Z');
  const prior={...engine.start({...input,runKind:'scheduled'},now).state,owner:'old',actionsRunId:'123',released:false};
  const manual={...engine.start({...input,mode:'resume',runKind:'manual',owner:'new'},manualNow).state,stage:'state',isOpen:true};
  const read=existing=>response({sha:'oldsha',content:Buffer.from(JSON.stringify(existing)).toString('base64')});
  const resumed=engine.advance(manual,read(prior),manualNow);
  assert.equal(resumed.state.actionsRunId,'123');assert.equal(resumed.state.nextStage,'pollRun');
  assert.equal(resumed.state.operationDeadline,manualNow+90*60000);
  assert.equal(resumed.state.scheduledCutoff,Date.parse('2026-10-02T11:30:00Z'));
  assert.equal(resumed.state.manualDeadlineOverride,true);
  const busy=engine.advance(manual,read({...prior,deadline:manualNow+10000}),manualNow);
  assert.equal(busy.state.errorCategory,'writer_busy');assert.equal(busy.op,null);
});
test('completed scheduled recovery makes no CAS, artifact or archive mutation',()=>{
  const previous={...input,owner:'old',released:true,screeningStatus:'complete',notionStatus:'complete',deployStatus:'verified'};
  const state={...engine.start({...input,runKind:'scheduled'},now).state,stage:'state',isOpen:true};
  const out=engine.advance(state,response({sha:'sha',content:Buffer.from(JSON.stringify(previous)).toString('base64')}),now);
  assert.equal(out.route,'done');assert.equal(out.op,null);assert.equal(out.state.screeningStatus,'already_complete');
});
test('exact request duplicates on later Actions pages fail closed',()=>{
  const state={...engine.start(input,now).state,stage:'findRun',lockSha:'sha',runPage:1};
  const runs=Array.from({length:100},(_,index)=>({id:index,display_title:index===0?'Daily screening | test-1 | 2026-10-02':'unrelated'}));
  const first=engine.advance(state,response({workflow_runs:runs}),now);
  assert.equal(first.state.stage,'findRun');assert.equal(first.state.runPage,2);
  const second=engine.advance(first.state,response({workflow_runs:[{id:101,display_title:'Daily screening | test-1 | 2026-10-02'}]}),now);
  assert.equal(second.state.errorCategory,'ambiguous_actions_runs');
});
test('artifact acceptance verifies immutable published bytes and main ancestry before Notion writes',()=>{
  const fs=require('node:fs');const crypto=require('node:crypto');
  const body={schemaVersion:'screening-export-v1',legacy:false,marketDate:input.marketDate,requestId:input.requestId,actionsRunId:'123',sourceGitCommit:'a'.repeat(40),runId:'r',generatedAt:'2026-10-02T10:00:00Z',revision:'b'.repeat(12),formulaVersions:{},coverage:{},funnel:growthFixture(),freshness:'current',strategies:{trust:[],growth:[],lowPosition:[]},selectedStocks:[]};
  const preimage=JSON.stringify(body);const hash=crypto.createHash('sha256').update(preimage).digest('hex');const raw=preimage.slice(0,-1)+',"payloadHash":"'+hash+'"}';
  const publication={requestId:body.requestId,marketDate:body.marketDate,runId:'r',payloadHash:hash,sourceGitCommit:body.sourceGitCommit,actionsRunId:'123',publishedGitCommit:'c'.repeat(40)};
  let out=engine.advance({...engine.start(input,now).state,stage:'artifactZip',lockSha:'sha',actionsRunId:'123',runHeadSha:body.sourceGitCommit},response({rawExport:raw,publication}),now);
  assert.equal(out.state.nextStage,'publicationExport');
  out=engine.advance(out.state,response({content:{sha:'next'}}),now);assert.ok(out.op.url.includes('?ref='+publication.publishedGitCommit));
  out=engine.advance(out.state,response({encoding:'base64',size:Buffer.byteLength(raw),content:Buffer.from(raw).toString('base64')}),now);
  assert.equal(out.state.stage,'publicationMain');assert.ok(out.op.url.endsWith(publication.publishedGitCommit+'...main'));
  const rejected=engine.advance(out.state,response({status:'diverged',base_commit:{sha:publication.publishedGitCommit}}),now);assert.equal(rejected.state.errorCategory,'publication_not_on_main');
  const verified=engine.advance(out.state,response({status:'ahead',base_commit:{sha:publication.publishedGitCommit}}),now);assert.equal(verified.state.nextStage,'liveProbe');assert.equal(verified.state.publicationStatus,'verified');
});
