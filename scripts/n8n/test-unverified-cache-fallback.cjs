const test = require('node:test');
const assert = require('node:assert/strict');
const engine = require('./engine.cjs');
const now = Date.parse('2026-10-14T12:49:00Z');
const state = {marketDate:'2026-10-14',previousSessionDate:'2026-10-13',requestId:'stockscreener:20261014:v1:retry2',owner:'fixture',mode:'screen',runKind:'scheduled',stage:'restoreState',restoreCacheCandidateDate:'2026-10-13',lockSha:'a'.repeat(40),deadline:now+3600000,siteUrl:'https://stockscreener.andyshih.uk',errorCategory:'restore_prior_custody',errorMessage:'restore_prior_custody'};
const response = day => ({statusCode:200,body:{content:Buffer.from(JSON.stringify(day)).toString('base64')}});
test('unfinished prior cache does not block current official-data acquisition',()=>{
  const output=engine.advance(state,response({marketDate:'2026-10-13',cacheStatus:'uploading',cacheManifestHash:'b'.repeat(64),cachePartsExpected:15,cachePartsVerified:0}),now);
  assert.equal(output.state.nextStage,'dispatch');
  assert.equal(output.state.restoreStatus,'missing');
  assert.equal(output.state.errorCategory,'');
  assert.ok(output.state.restoreWarning);
  assert.equal(output.state.restorePrior,undefined);
});
test('a cache claiming verification still requires valid custody before use',()=>{
  const output=engine.advance(state,response({marketDate:'2026-10-13',cacheStatus:'verified',cacheManifestHash:'b'.repeat(64)}),now);
  assert.equal(output.state.errorCategory,'');
  assert.equal(output.state.nextStage,'dispatch');
  assert.equal(output.state.restoreStatus,'missing');
  assert.match(output.state.restoreWarning,/restore_prior_custody/);
});

test('Notion restore outages discard all backup references and dispatch only fresh official inputs',()=>{
 for(const statusCode of [403,503]) {
  const input={...state,sourceMode:'publish',stage:'restorePage',retry:3,op:{target:'notion',method:'GET',url:'https://api.notion.com/v1/pages/example'},restoreManifestHash:'b'.repeat(64),restoreTransient:{files:{}},restorePartRefs:[{}],restoreRefsExecutionId:'fixture'};
  const fallback=engine.advance(input,{statusCode,body:{message:'private provider failure'}},now);
  assert.equal(fallback.state.nextStage,'dispatch');assert.equal(fallback.state.restoreStatus,'missing');assert.equal(fallback.state.restorePartRefs,undefined);assert.equal(fallback.state.restoreTransient,undefined);assert.doesNotMatch(fallback.state.restoreWarning,/private provider/);
  const dispatched=engine.advance(fallback.state,{statusCode:200,body:{content:{sha:'new'}}},now);
  assert.equal(dispatched.state.stage,'dispatch');assert.deepEqual(Object.keys(dispatched.op.body.inputs).sort(),['market_date','request_id','source_mode']);
  const conflict=engine.advance(fallback.state,{statusCode:409,body:{}},now);assert.equal(conflict.state.errorCategory,'writer_conflict');assert.equal(conflict.op,null);
 }
});
test('hash-invalid restore bytes fall back, while writer deadline still stops all work',()=>{
 const input={...state,stage:'restoreDownload',restoreFileMeta:[{name:'manifest.json',sha256:'b'.repeat(64),bytes:2}],restoreCursor:0};
 const output=engine.advance(input,{statusCode:200,body:{bytes:Buffer.from('{}').toString('base64')}},now);
 assert.equal(output.state.nextStage,'dispatch');assert.equal(output.state.restoreStatus,'missing');assert.match(output.state.restoreWarning,/restore_/);
 const expired=engine.advance({...input,deadline:now-1},{statusCode:503},now);assert.equal(expired.state.errorCategory,'writer_deadline');assert.equal(expired.op,null);
});
