'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const {installPegInline}=require('./build-peg-inline.cjs');
test('native PEG discovery is connected to main, guarded by CAS and commits only to state branch',()=>{
 const nodes=[],edges=[];
 const add=(name,type,typeVersion,parameters,credential,settings={})=>{const n={name,type,typeVersion,parameters,...settings};nodes.push(n);return n};
 const code=(name,jsCode)=>{new (Object.getPrototypeOf(async function(){}).constructor)(jsCode);return add(name,'n8n-nodes-base.code',2,{jsCode})};
 const connect=(a,b,i=0)=>edges.push([a.name,b.name,i]);
 const advanceNode={name:'advance'};
 const result=installPegInline({add,code,connect,advanceNode});
 assert.equal(result.entry.name,'Capture PEG discovery parent state');
 assert.ok(nodes.find(n=>n.name==='Commit approved source manifest'));
 assert.match(nodes.find(n=>n.name==='Prepare source manifest commit').parameters.jsCode,/branch:'n8n-state'/);
 assert.equal(nodes.some(n=>n.type==='n8n-nodes-base.executeWorkflow'),false);
 assert.ok(edges.some(([a,b])=>a==='Return pinned PEG manifest to main'&&b==='advance'));
 assert.ok(edges.some(([a,b])=>a==='Stop on PEG discovery failure'&&b==='advance'));
});
test('registry or Searx outage records candidate-scoped unavailable evidence, including zero missing stocks',async()=>{
 const nodes=[];const add=(name,type,v,parameters)=>{const n={name,type,parameters};nodes.push(n);return n};
 const code=(name,jsCode)=>add(name,'code',2,{jsCode});
 installPegInline({add,code,connect:()=>{},advanceNode:{name:'advance'}});
 const run=new (Object.getPrototypeOf(async function(){}).constructor)('$input','$',nodes.find(n=>n.name==='Initialize PEG source discovery').parameters.jsCode);
 for(const missing of [0,1]){
  const state={marketDate:'2026-11-03',requestId:'request',pegCandidateSha256:'a'.repeat(64),pegPreview:{marketDate:'2026-11-03',requestId:'request',prepareRunId:'123',prepareRunAttempt:1,candidateSha256:'a'.repeat(64),stocks:Array.from({length:100},(_,i)=>({code:String(1000+i),name:'Company',pegReview:{status:i<missing?'needs_review':'available'},currentPeriod:null}))}};
  const row={id:1,revision:3,lease_until:Date.now()+600000,searx_url:'',state_json:JSON.stringify({marketDate:'2026-11-03',leaseOwner:'42',braveUsage:{date:'2026-11-03',used:7,reserved:0},leaseBraveReservation:0})};
  const lookup=name=>({first:()=>({json:name==='Verify discovery lease'?row:{state}})});
  const out=await run({first:()=>({json:{statusCode:503}})},lookup);
  assert.equal(out[0].json.initReady,false);assert.equal(out[0].json.state.manifest.stocks.length,missing);
  assert.equal(out[0].json.state.manifest.searchUsage.brave,7);
  if(missing)assert.equal(out[0].json.state.manifest.stocks[0].reason,'source_unavailable');
  const finish=new (Object.getPrototypeOf(async function(){}).constructor)('$input','$',nodes.find(n=>n.name==='Finish PEG manifest').parameters.jsCode);
  const bound=(await finish({first:()=>out[0]},lookup))[0].json;assert.equal(bound.manifestReady,true);
  const save=new (Object.getPrototypeOf(async function(){}).constructor)('$input','$','$execution',nodes.find(n=>n.name==='Prepare durable search results').parameters.jsCode);
  const saved=await save({first:()=>({json:bound})},lookup,{id:'42'});assert.equal(saved[0].json.status,'finished');
 }
});
test('empty CAS output fails explicitly and never permits manifest commit',async()=>{
 const nodes=[];const edges=[];const add=(name,type,v,parameters,credential,settings={})=>{const n={name,type,parameters,...settings};nodes.push(n);return n};const code=(name,jsCode)=>add(name,'code',2,{jsCode});
 installPegInline({add,code,connect:(a,b,i=0)=>edges.push([a.name,b.name,i]),advanceNode:{name:'advance'}});
 for(const name of ['Read durable PEG progress','Claim PEG progress with CAS','Persist search results with CAS','Save final PEG outcome with CAS'])assert.equal(nodes.find(n=>n.name===name).alwaysOutputData,true,name);
 const run=new (Object.getPrototypeOf(async function(){}).constructor)('$input','$','$execution',nodes.find(n=>n.name==='Verify saved PEG search results').parameters.jsCode);
 const out=await run({first:()=>({json:{}})},()=>({first:()=>({json:{state:{pegCandidateSha256:'a'.repeat(64),requestId:'r'}}})}),{id:'42'});
 assert.equal(out[0].json.valid,false);assert.ok(edges.some(([a,b,i])=>a==='PEG search results saved?'&&b==='Prepare failed PEG quota release'&&i===1));
});
test('discovery captures the current router item, not an earlier router execution',async()=>{
 const nodes=[];const add=(name,type,v,parameters)=>{const n={name,type,parameters};nodes.push(n);return n};const code=(name,jsCode)=>add(name,'code',2,{jsCode});
 installPegInline({add,code,connect:()=>{},advanceNode:{name:'advance'}});
 const run=new (Object.getPrototypeOf(async function(){}).constructor)('$input',nodes.find(n=>n.name==='Capture PEG discovery parent state').parameters.jsCode);
 const current={stage:'pegDiscovery',requestId:'current',pegCandidateSha256:'a'.repeat(64)};
 assert.deepEqual((await run({first:()=>({json:{state:current}})}))[0].json.state,current);
 for(const name of ['Prepare discovery lease','Initialize PEG source discovery','Finish PEG manifest','Return pinned PEG manifest to main'])assert.match(nodes.find(n=>n.name===name).parameters.jsCode,/Capture PEG discovery parent state/);
});
