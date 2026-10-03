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
 assert.equal(graph.active,false);assert.equal(graph.settings.saveDataSuccessExecution,'none');assert.equal(graph.settings.timezone,'Asia/Taipei');
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
});
