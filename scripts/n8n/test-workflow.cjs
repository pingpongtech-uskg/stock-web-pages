const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const graph=JSON.parse(fs.readFileSync(path.join(__dirname,'stockscreener.workflow.json'),'utf8'));
test('normal manual entry dispatches real work; diagnostics have an explicit separate choice',()=>{
 const input=graph.nodes.find(node=>node.name==='Operator inputs');const assignments=input.parameters.assignments.assignments;
 assert.equal(assignments.find(field=>field.name==='mode').value,'screen');
 assert.ok(input.notes.includes('diagnose'));
 assert.ok(graph.nodes.some(node=>node.name.includes('Diagnostics')&&node.name.includes('Notion')));
});
test('canvas exposes native dispatch and named business archive, publication and verification stages',()=>{
 const node=graph.nodes.find(node=>node.name==='GitHub Dispatch Actions');assert.ok(node);assert.equal(node.type,'n8n-nodes-base.github');assert.equal(node.parameters.operation,'dispatch');assert.equal(node.alwaysOutputData,true);assert.equal(node.retryOnFail,undefined);
 for(const name of ['Confirm GitHub main publication','Create Notion daily record','Create Notion inline daily database','Create missing stock row','Read back Notion rows and values','Verify live exact payload','Show durable operation outcome'])assert.ok(graph.nodes.some(node=>node.name===name),name);
 assert.equal(graph.active,false);assert.equal(graph.settings.saveDataSuccessExecution,'all');assert.equal(graph.settings.timezone,'Asia/Taipei');
});
test('native GitHub dispatch inputs satisfy its actual JSON.parse preflight contract',()=>{
 const node=graph.nodes.find(node=>node.name==='GitHub Dispatch Actions');
 const input={request_id:'stockscreener:20261002:v1',market_date:'2026-10-02'};
 const expression=node.parameters.inputs.replace(/^=\{\{\s*|\s*\}\}$/g,'');
 const value=new Function('$json','return ('+expression+');')({op:{body:{inputs:input}}});
 assert.equal(typeof value,'string');assert.deepEqual(JSON.parse(value),input);
 assert.throws(()=>JSON.parse(input),SyntaxError); // Previous object-valued expression fails before any GitHub request.
});
test('expired writer records terminal outcome and cannot enter a credential request again',()=>{
 const node=graph.nodes.find(node=>node.name==='Gate writer deadline and allowed origins');
 const evaluate=new Function('$input','Date',node.parameters.jsCode);
 const original={state:{stage:'dispatch',lockSha:'observed',deadline:100},op:{url:'https://api.github.com/repos/pingpongtech-uskg/stock-web-pages/actions/workflows/daily.yml/dispatches'},route:'github',ledgerRequired:false};
 const result=evaluate({first:()=>({json:original})},{now:()=>101})[0].json;
 assert.equal(result.state.stage,'done');assert.equal(result.op,null);assert.equal(result.ledgerRequired,true);
 const afterLedger={...result,ledgerRequired:false};
 assert.equal(evaluate({first:()=>({json:afterLedger})},{now:()=>102})[0].json.ledgerRequired,false);
 const branch=graph.nodes.find(node=>node.name==='Persist expired-owner outcome before showing result');assert.ok(branch);
 assert.equal(graph.connections[branch.name].main[0][0].node,'Prepare sanitized durable progress');
});
test('live publication verification preserves exact JSON bytes rather than parsed text numbers',async()=>{
 for(const name of ['Probe live publication before archive','Verify live exact payload'])assert.equal(graph.nodes.find(node=>node.name===name).parameters.options.response.response.responseFormat,'file');
 const node=graph.nodes.find(node=>node.name==='Restore exact live bytes and current stage');assert.ok(node);
 const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;const evaluate=new AsyncFunction('$input','$',node.parameters.jsCode);
 const raw='{"value":130.0,"absent":null}';const item={json:{statusCode:200,headers:{'content-type':'application/json'}},binary:{data:{}}};
 const output=await evaluate.call({helpers:{getBinaryDataBuffer:async()=>Buffer.from(raw)}},{first:()=>item},()=>({item:{json:{state:{stage:'liveVerify'}}}}));
 assert.equal(output[0].json.response.body,raw);assert.equal(output[0].json.state.stage,'liveVerify');
 const failed=await evaluate.call({}, {first:()=>({json:{error:'network'}})},()=>({item:{json:{state:{stage:'liveVerify'}}}}));assert.equal(failed[0].json.response.error,'network');
 assert.equal(failed[0].json.response.liveReadError,'live_binary_missing');
 const large=await evaluate.call({helpers:{getBinaryDataBuffer:async()=>Buffer.alloc(3000001)}},{first:()=>item},()=>({item:{json:{state:{stage:'liveVerify'}}}}));assert.equal(large[0].json.response.liveReadError,'live_file_too_large');assert.equal(large[0].json.response.statusCode,200);
 const unreadable=await evaluate.call({helpers:{getBinaryDataBuffer:async()=>{throw Error('storage');}}},{first:()=>item},()=>({item:{json:{state:{stage:'liveVerify'}}}}));assert.equal(unreadable[0].json.response.liveReadError,'live_binary_read_failed');
 const engine=require('./engine.cjs');const state={stage:'liveVerify',marketDate:'2026-10-02',requestId:'unit-only',siteUrl:'https://stockscreener.andyshih.uk',lockSha:'known',deadline:100000,op:{method:'GET',url:'https://stockscreener.andyshih.uk/data/screening-export.json'}};
 const persisted=engine.advance(state,large[0].json.response,0);assert.equal(persisted.state.deployError,'live_file_too_large');assert.equal(persisted.delaySeconds,15);
 const limited=engine.advance(state,{...large[0].json.response,statusCode:429,headers:{'retry-after':'7'}},0);assert.equal(limited.delaySeconds,7);
});

test('full cache roster fetch is anonymous and origin gate permits only exact immutable published roster',()=>{const n=graph.nodes.find(n=>n.name==='Read full published roster for cache');assert.equal(n.parameters.authentication,'none');assert.equal(n.credentials,undefined);assert.equal(n.parameters.sendHeaders,false);assert.equal(n.parameters.options.redirect.redirect.followRedirects,false);const gate=graph.nodes.find(n=>n.name==='Gate writer deadline and allowed origins'),run=new Function('$input','Date',gate.parameters.jsCode);const commit='a'.repeat(40),url='https://raw.githubusercontent.com/pingpongtech-uskg/stock-web-pages/'+commit+'/public/data/latest.json',state={stage:'cacheLatest',publication:{publishedGitCommit:commit},siteUrl:'https://stockscreener.andyshih.uk'};const check=(changes={},patch={})=>run({first:()=>({json:{state:{...state,...patch},route:'public',op:{url,method:'GET',...changes}}})},Date);assert.doesNotThrow(()=>check());for(const changed of [{url:url.replace(commit,'b'.repeat(40))},{url:url+'?other=1'},{method:'POST'},{url:url.replace('/latest.json','/screening-export.json')}])assert.throws(()=>check(changed),/request_origin_rejected/);assert.throws(()=>check({}, {stage:'liveProbe'}),/request_origin_rejected/);assert.throws(()=>check({}, {publication:{publishedGitCommit:'main'}}),/request_origin_rejected/);});

test('automatic source recovery exposes exact failed-run job and artifact metadata stages',()=>{for(const name of ['Inspect failed source job steps','Check failed run export artifacts']){const n=graph.nodes.find(n=>n.name===name);assert.ok(n);assert.equal(n.credentials.githubApi.id,'VGYqVCElPfvn333j');assert.equal(n.parameters.method,'={{ $json.op.method }}');assert.equal(graph.connections[n.name].main[0][0].node,'Restore current stage after credential response');}});

test('primary retains successful, failed and manual runs without incremental execution snapshots',()=>{assert.equal(graph.settings.saveDataSuccessExecution,'all');assert.equal(graph.settings.saveDataErrorExecution,'all');assert.equal(graph.settings.saveManualExecutions,true);assert.equal(graph.settings.saveExecutionProgress,false);});
