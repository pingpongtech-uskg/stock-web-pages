const test=require('node:test');const assert=require('node:assert/strict');let helpers={};try{helpers=require('./outcome.cjs');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
test('durable outcome distinguishes diagnostics and preserves independent statuses and exact counts',()=>{
 assert.equal(typeof helpers.operationOutcome,'function');
 const base={marketDate:'2026-10-02',requestId:'stockscreener:20261002:v1',actionsRunId:'123',notionPageId:'11111111-1111-1111-1111-111111111111',screeningStatus:'complete',notionStatus:'complete',deployStatus:'pending',expectedCount:0,archivedCount:0,stage:'done'};
 const out=helpers.operationOutcome({...base,errorCategory:'deploy_pending'});assert.equal(out.expectedCount,0);assert.equal(out.archivedCount,0);assert.equal(out.outcome,'deployment_pending');assert.equal(out.actionsUrl,'https://github.com/pingpongtech-uskg/stock-web-pages/actions/runs/123');
 assert.equal(helpers.operationOutcome({...base,screeningStatus:'diagnostic_verified',notionStatus:'credential_verified',deployStatus:'not_tested'}).outcome,'diagnostics_only');
 assert.equal(helpers.operationOutcome({...base,screeningStatus:'already_complete',deployStatus:'verified'}).outcome,'already_complete');
 assert.equal(helpers.operationOutcome({...base,screeningStatus:'failed',notionStatus:'failure_metadata',errorCategory:'screening_failed'}).outcome,'failed');
});
test('outcome never persists signed URL, payload, auth data or remote query strings',()=>{
 assert.equal(typeof helpers.operationOutcome,'function');
 const out=helpers.operationOutcome({stage:'done',marketDate:'2026-10-02',owner:'a',errorMessage:'failed https://host.example/file?signature=private',op:{url:'https://host.example/file?secret=private'},payload:{secret:'private'},publication:{publishedGitCommit:'a'.repeat(40),url:'https://secret'}});
 const raw=JSON.stringify(out);assert.equal(raw.includes('private'),false);assert.equal(raw.includes('https://secret'),false);assert.equal(Object.hasOwn(out,'payload'),false);assert.equal(Object.hasOwn(out,'op'),false);assert.equal(out.publishedGitCommit,'a'.repeat(40));
});
test('native dispatch 204/empty success and failed transport always continue exact-run recovery',()=>{
 assert.equal(typeof helpers.nativeDispatchResponse,'function');
 assert.equal(helpers.nativeDispatchResponse({}).statusCode,204);
 assert.equal(helpers.nativeDispatchResponse({error:{statusCode:403,message:'Forbidden'}}).statusCode,403);
 assert.equal(helpers.nativeDispatchResponse({error:{statusCode:403,message:'Forbidden'}}).error,undefined);
 assert.equal(helpers.nativeDispatchResponse({error:'ETIMEDOUT'}).statusCode,503);
 assert.equal(helpers.nativeDispatchResponse({error:{httpCode:'429'}}).statusCode,429);
 assert.equal(helpers.nativeDispatchResponse({error:{httpCode:'429',headers:{'retry-after':'10'}}}).headers['retry-after'],'10');
});
