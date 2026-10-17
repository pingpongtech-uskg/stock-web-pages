const test=require('node:test'),assert=require('node:assert/strict'),engine=require('./engine.cjs');
const now=Date.parse('2026-10-16T10:00:00Z'),sha='a'.repeat(40);
const input={marketDate:'2026-10-16',requestId:'stockscreener:20261016:v1',owner:'new',mode:'screen',runKind:'scheduled',siteUrl:'https://stockscreener.andyshih.uk'};
const response=(body,statusCode=200)=>({statusCode,body});
const state={...engine.start(input,now).state,stage:'publicationMain',actionsRunId:'123',runHeadSha:sha,publication:{publishedGitCommit:'b'.repeat(40)},payloadHash:'c'.repeat(64)};
test('verified main requests credentialed deployment marker then checks public bytes',()=>{
 const read=engine.advance(state,response({status:'ahead',base_commit:{sha:state.publication.publishedGitCommit}}),now);
 assert.equal(read.state.stage,'deployTriggerRead');assert.equal(read.op.method,'GET');assert.equal(read.state.deployRequestAttempt,1);
 const write=engine.advance(read.state,response({},404),now);
 assert.equal(write.state.stage,'deployTriggerWrite');assert.equal(write.op.method,'PUT');assert.equal(write.op.body.branch,'main');
 const marker=JSON.parse(Buffer.from(write.op.body.content,'base64').toString());
 assert.deepEqual(marker,{schemaVersion:'deployment-request-v1',marketDate:input.marketDate,requestId:input.requestId,actionsRunId:'123',sourceGitCommit:sha,publishedGitCommit:'b'.repeat(40),payloadHash:'c'.repeat(64),attempt:1});
 const published=engine.advance(write.state,response({commit:{sha:'d'.repeat(40)}},201),now);
 assert.equal(published.state.nextStage,'liveVerify');assert.equal(published.state.deployRequestCommit,'d'.repeat(40));assert.notEqual(published.state.deployStatus,'verified');
});
test('deployment marker update uses exact old SHA and rejects invalid marker schema',()=>{
 const read={...state,stage:'deployTriggerRead',deployRequestAttempt:2};
 const marker={schemaVersion:'deployment-request-v1',marketDate:'2026-10-15',requestId:'old',attempt:1};
 const existing={encoding:'base64',size:JSON.stringify(marker).length,sha:'e'.repeat(40),content:Buffer.from(JSON.stringify(marker)).toString('base64')};
 const write=engine.advance(read,response(existing),now);assert.equal(write.op.body.sha,existing.sha);
 const malformed=engine.advance(read,response({...existing,content:Buffer.from('{}').toString('base64')}),now);assert.equal(malformed.state.errorCategory,'deploy_trigger_schema');
});
test('same producer resumes expired deployment polling without duplicate dispatch',()=>{
 const existing={...state,owner:'old',released:true,stage:'done',screeningStatus:'complete',publicationStatus:'verified',deployStatus:'failed',deployAttempts:20,deployRequestAttempt:2,notionStatus:'deployment_pending'};
 const read={...engine.start(input,now).state,stage:'state',isOpen:true};
 const out=engine.advance(read,response({sha:'f'.repeat(40),content:Buffer.from(JSON.stringify(existing)).toString('base64')}),now);
 assert.equal(out.state.nextStage,'pollRun');assert.equal(out.state.actionsRunId,'123');assert.equal(out.state.deployAttempts,0);assert.equal(out.state.deployRequestAttempt,2);
});
test('missing archive identifiers recover schema after verified live deployment',()=>{
 const out=engine.advance({...state,stage:'liveVerify',deployAttempts:20,expectedCount:1,archivedCount:0,payload:{selectedStocks:[{}]}},response({},404),now);
 assert.equal(out.state.nextStage,'rootSchema');assert.equal(out.state.deployStatus,'failed');
});
test('unverified website never starts auxiliary cache after row verification',()=>{
 const out=engine.advance({...pubFallback(),stage:'verifyRows',deployStatus:'failed'},response({results:[],has_more:false}),now);
 assert.equal(out.state.nextStage,'summaryRead');assert.notEqual(out.state.nextStage,'cacheRun');
});
function pubFallback(){return {...state,payload:{...state.payload,selectedStocks:[]},expectedCount:0};}
