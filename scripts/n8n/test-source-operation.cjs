const test=require('node:test');const assert=require('node:assert/strict');let helper={};try{helper=require('./source-operation.cjs');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
const base='a'.repeat(40),target='b'.repeat(40),baseTree='c'.repeat(40),tree='d'.repeat(40),blob='e'.repeat(40);
const plan={mode:'prepare_feature',baseSha:base,featureBaseSha:base,targetSha:target,baseTreeSha:baseTree,targetTreeSha:tree,blobs:[{sha:blob,content:Buffer.from('local fixture').toString('base64')}],treeEntries:[{path:'scripts/local-fixture.py',mode:'100644',type:'blob',sha:blob}],commit:{message:'test: local fixture only',author:{name:'Local tester',email:'local@example.test',date:'2026-10-03T01:00:00Z'},committer:{name:'Local tester',email:'local@example.test',date:'2026-10-03T01:00:00Z'},parents:[base],tree}};
const ok=body=>({statusCode:200,body});
test('source helper validates immutable plans and starts read-only with no primary or Notion operations',()=>{
 assert.equal(typeof helper.sourceStart,'function');assert.equal(helper.sourceStart({mode:'inspect'},0).op.method,'GET');
 assert.throws(()=>helper.sourceStart({...plan,targetSha:'bad'},0),/source_input/);assert.throws(()=>helper.sourceStart({...plan,treeEntries:[{path:'../escape',mode:'100644',type:'blob',sha:blob}]},0),/source_manifest/);
 assert.throws(()=>helper.sourceStart({...plan,commit:{...plan.commit,parents:[target]}},0),/source_manifest/);
});
test('publication creates only reviewed Git objects then rechecks refs before nonforced feature update',()=>{
 let out=helper.sourceStart(plan,0);const writes=[];
 const bodies={main:{object:{sha:base}},feature:{object:{sha:base}},baseCommit:{sha:base,tree:{sha:baseTree}},blob:{sha:blob},tree:{sha:tree},commit:{sha:target},featureRecheck:{object:{sha:base}},mainRecheck:{object:{sha:base}},featureWrite:{object:{sha:target}},featureVerify:{object:{sha:target}}};
 for(let i=0;i<12&&out.op;i++){if(out.op.method!=='GET')writes.push(out.op);out=helper.sourceAdvance(out.state,ok(bodies[out.state.stage]),0);}
 assert.equal(out.state.outcome,'feature_verified');assert.equal(writes.length,4);assert.equal(writes.at(-1).body.force,false);assert.ok(writes.at(-1).url.endsWith('/git/refs/heads/fix/n8n-daily-screening'));
 let moved=helper.sourceStart(plan,0);moved=helper.sourceAdvance(moved.state,ok({object:{sha:target}}),0);assert.equal(moved.state.errorCategory,'main_changed');assert.equal(moved.op,null);
});
test('main promotion requires exact feature CI workflow/head/repository and nonforced refs',()=>{
 const promote={mode:'promote_main',baseSha:base,targetSha:target,targetTreeSha:tree,ciRunId:'123'};let out=helper.sourceStart(promote,0);
 const bodies={main:{object:{sha:base}},feature:{object:{sha:target}},ciWorkflow:{id:77},ciRun:{id:123,workflow_id:77,head_sha:target,head_branch:'fix/n8n-daily-screening',event:'push',status:'completed',conclusion:'success',repository:{full_name:'pingpongtech-uskg/stock-web-pages'}},targetCommit:{sha:target,tree:{sha:tree},parents:[{sha:base}]},mainRecheck:{object:{sha:base}},mainWrite:{object:{sha:target}},mainVerify:{object:{sha:target}}};
 for(let i=0;i<10&&out.op;i++){if(out.state.stage==='mainWrite')assert.deepEqual(out.op.body,{sha:target,force:false});out=helper.sourceAdvance(out.state,ok(bodies[out.state.stage]),0);}
 assert.equal(out.state.outcome,'main_verified');
 const wrong=helper.sourceAdvance({plan:promote,stage:'ciRun',deadline:999,workflowId:77},ok({...bodies.ciRun,head_sha:base}),0);assert.equal(wrong.state.errorCategory,'ci_gate');assert.equal(wrong.op,null);
});
const probe={mode:'dispatch_probe',probeHeadSha:target,marketDate:'2026-10-02',requestId:'institutional-probe:20261002:local-only'};
test('one probe dispatch uses stringified institutional_probe inputs and recovers exact run after ambiguous response',()=>{
 let out=helper.sourceStart(probe,0);out=helper.sourceAdvance(out.state,ok({object:{sha:target}}),0);out=helper.sourceAdvance(out.state,ok({id:88}),0);out=helper.sourceAdvance(out.state,ok({workflow_runs:[]}),0);
 assert.equal(out.route,'native');assert.equal(out.ledgerRequired,true);assert.deepEqual(out.op.body.inputs,{request_id:probe.requestId,market_date:probe.marketDate,source_mode:'institutional_probe'});
 out=helper.sourceAdvance(out.state,{statusCode:503,error:true},0);assert.equal(out.op.method,'GET');assert.equal(out.state.dispatchIntent,true);
 out=helper.sourceAdvance(out.state,ok({workflow_runs:[]}),1000);assert.equal(out.op.method,'GET');assert.equal(out.route,'github');
 const matched=helper.sourceAdvance(out.state,ok({workflow_runs:[{id:456,workflow_id:88,head_sha:target,head_branch:'main',event:'workflow_dispatch',head_repository:{full_name:'pingpongtech-uskg/stock-web-pages'},display_title:`Daily screening | ${probe.requestId} | ${probe.marketDate}`}]}),1000);assert.equal(matched.state.runId,'456');assert.equal(matched.state.stage,'pollRun');
});
test('helper deadlines, HTTP errors and outputs do not expose payloads or signed URLs',()=>{
 const out=helper.sourceAdvance({plan:probe,stage:'findRun',deadline:5},ok({}),6);assert.equal(out.state.errorCategory,'source_deadline');assert.equal(out.op,null);
 const denied=helper.sourceAdvance({plan:probe,stage:'dispatch',deadline:999}, {statusCode:403,body:{message:'https://secret?token=value'}},0);assert.equal(denied.state.errorCategory,'github_http_403');
 assert.equal(JSON.stringify(helper.sourceOutcome({...denied.state,signedUrl:'https://secret',rawRows:[{token:'private'}]})).includes('secret'),false);
});
const run={id:456,workflow_id:88,head_sha:target,head_branch:'main',event:'workflow_dispatch',head_repository:{full_name:'pingpongtech-uskg/stock-web-pages'},display_title:`Daily screening | ${probe.requestId} | ${probe.marketDate}`};
test('probe lookup scans all pages before rejecting duplicate exact requests',()=>{
 const state={plan:probe,stage:'findRun',deadline:999999,workflowId:88,startedAt:0};const first=helper.sourceAdvance(state,ok({workflow_runs:[run,...Array.from({length:99},(_,id)=>({id,display_title:'unrelated'}))]}),0);
 assert.equal(first.state.stage,'findRun');assert.equal(first.state.runPage,2);
 const duplicate=helper.sourceAdvance(first.state,ok({workflow_runs:[run]}),0);assert.equal(duplicate.state.errorCategory,'ambiguous_probe_runs');
});
test('probe artifact source is authenticated by exact run/workflow/head and signed storage has no credentials',()=>{
 let out=helper.sourceStart({...probe,mode:'read_probe',runId:'456'},0);out=helper.sourceAdvance(out.state,ok({object:{sha:target}}),0);out=helper.sourceAdvance(out.state,ok({id:88,state:'active'}),0);
 out=helper.sourceAdvance(out.state,ok({...run,status:'in_progress'}),0);assert.equal(out.delaySeconds,15);
 out=helper.sourceAdvance(out.state,ok({...run,status:'completed',conclusion:'success',run_attempt:1}),0);
 const artifact={id:900,name:'institutional-probe',expired:false,size_in_bytes:100,workflow_run:{id:456,head_sha:target}};
 out=helper.sourceAdvance(out.state,ok({total_count:1,artifacts:[artifact]}),0);assert.equal(out.state.stage,'artifactRedirect');
 out=helper.sourceAdvance(out.state,{statusCode:302,headers:{location:'https://store.blob.core.windows.net/approved?signature=transient'}},0);assert.equal(out.route,'zip');assert.equal(out.op.body,undefined);assert.equal(JSON.stringify(helper.sourceOutcome(out.state)).includes('signature'),false);
 out=helper.sourceAdvance(out.state,ok({}),0);assert.equal(out.state.errorCategory,'probe_artifact_schema');
 const blocked=helper.sourceAdvance({plan:probe,stage:'artifactRedirect',deadline:999}, {statusCode:302,headers:{location:'https://attacker.test/payload'}},0);assert.equal(blocked.state.errorCategory,'artifact_storage_origin');
});
test('publication guard mismatches and unknown responses stop before visible writes',()=>{
 for(const [stage,body,error] of [['baseCommit',{sha:base,tree:{sha:target}},'base_tree_mismatch'],['blob',{sha:target},'blob_sha_mismatch'],['tree',{sha:target},'tree_sha_mismatch'],['commit',{sha:base},'commit_sha_mismatch'],['featureRecheck',{object:{sha:target}},'feature_changed'],['mainRecheck',{object:{sha:target}},'main_changed'],['featureWrite',{object:{sha:base}},'ref_write_mismatch'],['mainVerify',{object:{sha:base}},'ref_readback_mismatch'],['feature',{object:{sha:base}},'feature_changed'],['unknown',{},'source_stage']]){
  const input={...plan,mode:stage==='feature'?'promote_main':plan.mode};const out=helper.sourceAdvance({plan:input,stage,blobIndex:0,deadline:999},ok(body),0);assert.equal(out.state.errorCategory,error);assert.equal(out.op,null);
 }
 assert.equal(helper.sourceAdvance({plan,stage:'tree',deadline:999},{statusCode:503},0).state.errorCategory,'github_http_503');
 assert.equal(helper.sourceAdvance({plan,stage:'main',deadline:999},ok('not JSON'),0).state.errorCategory,'github_response_schema');
 const already=helper.sourceAdvance({plan,stage:'feature',deadline:999},ok({object:{sha:target}}),0);assert.equal(already.state.outcome,'feature_verified');assert.equal(already.op,null);
});
test('real artifact redirect can have an empty body and GitHub error bodies do not mask HTTP status',()=>{const state={plan:probe,stage:'artifactRedirect',deadline:999};const out=helper.sourceAdvance(state,{statusCode:302,body:'',headers:{location:'https://store.blob.core.windows.net/file?signature=transient'}},0);assert.equal(out.route,'zip');assert.equal(helper.sourceAdvance(state,{statusCode:403,body:'Forbidden'},0).state.errorCategory,'github_http_403');});
function sizedManifest(bytes){const input={...plan,commit:{...plan.commit,message:''}};const overhead=Buffer.byteLength(JSON.stringify(input),'utf8');return {...input,commit:{...input.commit,message:'x'.repeat(bytes-overhead)}};}
test('publication manifest accepts exactly 2000000 UTF-8 bytes and rejects one extra byte',()=>{
 const exact=sizedManifest(2000000);assert.equal(Buffer.byteLength(JSON.stringify(exact),'utf8'),2000000);
 assert.equal(helper.sourceStart(exact,0).op.method,'GET');
 const overflow={...exact,commit:{...exact.commit,message:exact.commit.message+'x'}};
 assert.equal(Buffer.byteLength(JSON.stringify(overflow),'utf8'),2000001);assert.throws(()=>helper.sourceStart(overflow,0),/source_manifest/);
});
test('publication manifest cap counts Unicode UTF-8 bytes rather than character length',()=>{
 const input={...plan,commit:{...plan.commit,message:'中'.repeat(600000)}};
 assert.ok(JSON.stringify(input).length<2000000);assert.ok(Buffer.byteLength(JSON.stringify(input),'utf8')>1000000);
 assert.equal(helper.sourceStart(input,0).op.method,'GET');
 const overflow={...input,commit:{...input.commit,message:'中'.repeat(700000)}};
 assert.ok(JSON.stringify(overflow).length<2000000);assert.ok(Buffer.byteLength(JSON.stringify(overflow),'utf8')>2000000);
 assert.throws(()=>helper.sourceStart(overflow,0),/source_manifest/);
});
test('larger bounded plans retain 100-item path SHA and base guards',()=>{
 const large=sizedManifest(1600000);const hundred={...large,blobs:Array.from({length:100},()=>plan.blobs[0]),treeEntries:Array.from({length:100},(_,i)=>({...plan.treeEntries[0],path:`scripts/fixture-${i}.py`}))};
 assert.equal(helper.sourceStart(hundred,0).state.plan.blobs.length,100);
 for(const invalid of [{...hundred,blobs:[...hundred.blobs,plan.blobs[0]]},{...hundred,treeEntries:[...hundred.treeEntries,plan.treeEntries[0]]},{...large,treeEntries:[{...plan.treeEntries[0],path:'../escape'}]},{...large,blobs:[{...plan.blobs[0],sha:'invalid'}]},{...large,baseTreeSha:'invalid'}])assert.throws(()=>helper.sourceStart(invalid,0),/source_manifest/);
});
test('canonical generated-source-sized base64 plan remains within 2MB publication envelope',()=>{const raw=Buffer.alloc(1170000,120),sha=require('node:crypto').createHash('sha1').update(Buffer.from('blob '+raw.length+'\0')).update(raw).digest('hex');const input={...plan,blobs:[{sha,content:raw.toString('base64')}],treeEntries:[{...plan.treeEntries[0],sha}]};const bytes=Buffer.byteLength(JSON.stringify(input),'utf8');assert.ok(bytes>1500000&&bytes<2000000);assert.equal(helper.sourceStart(input,0).op.method,'GET');});
