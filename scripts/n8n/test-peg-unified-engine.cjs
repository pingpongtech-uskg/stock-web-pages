'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const engine=require('./engine.cjs');
const now=Date.parse('2026-11-03T11:00:00Z');
const base={marketDate:'2026-11-03',requestId:'test-1',mode:'screen',runKind:'scheduled',sourceMode:'publish',siteUrl:'https://stockscreener.andyshih.uk',owner:'700',lockSha:'blob',deadline:now+3600000,startedAt:now};
const response=body=>({statusCode:200,body});
function committed(out) { assert.equal(out.state.stage,'checkpoint'); return engine.advance(out.state,response({content:{sha:'new-sha'}}),now); }
const run={id:123,run_attempt:1,display_title:'Daily PEG prepare | test-1 | 2026-11-03',event:'workflow_dispatch',head_branch:'main',path:'.github/workflows/daily.yml',head_sha:'a'.repeat(40),repository:{id:1273106108},head_repository:{id:1273106108},status:'completed',conclusion:'success'};
const artifact={id:456,digest:'sha256:'+'d'.repeat(64),size_in_bytes:1024,name:'peg-candidate-123-1',expired:false,workflow_run:{id:123,head_sha:run.head_sha,repository_id:1273106108,head_repository_id:1273106108}};
const preview={marketDate:base.marketDate,requestId:base.requestId,prepareRunId:'123',prepareRunAttempt:1,sourceGitCommit:run.head_sha,candidateSha256:'b'.repeat(64),stocks:Array.from({length:100},(_,i)=>({code:String(1000+i),name:'Company',pegReview:{status:'needs_review'},currentPeriod:null}))};
test('preparation dispatch is intent-checkpointed and uncertain receipt never redispatches',()=>{
 let out=engine.advance({...base,stage:'pegFindPrepare',pegPhase:'prepare'},response({workflow_runs:[]}),now);
 assert.equal(out.state.nextStage,'pegDispatchPrepare');assert.equal(out.state.pegPrepareIntent,true);
 out=committed(out); assert.equal(out.state.stage,'pegDispatchPrepare');assert.equal(out.op.body.inputs.source_mode,'prepare_peg');
 out=engine.advance(out.state,{statusCode:503,error:true},now);assert.equal(out.state.stage,'pegFindPrepare');assert.equal(out.op.method,'GET');
});
test('authenticated prepare artifact and exact preview lead to pinned final dispatch',()=>{
 let out=engine.advance({...base,stage:'pegFindPrepare',pegPrepareIntent:true,pegPrepareStartedAt:now},response({workflow_runs:[run]}),now);out=committed(out);
 assert.equal(out.state.stage,'pegPollPrepare');out=engine.advance(out.state,response(run),now);out=committed(out);
 assert.equal(out.state.stage,'pegArtifactList');out=engine.advance(out.state,response({total_count:1,artifacts:[artifact]}),now);
 assert.equal(out.state.stage,'pegArtifactRedirect');assert.equal(out.state.pegArtifactSha256,'d'.repeat(64));assert.equal(out.state.pegArtifactBytes,1024);out=engine.advance(out.state,{statusCode:302,body:'',headers:{location:'https://x.actions.githubusercontent.com/file'}},now);
 assert.equal(out.state.stage,'pegArtifactZip');out=engine.advance(out.state,response({preview,candidateSha256:preview.candidateSha256}),now);out=committed(out);
 assert.equal(out.state.stage,'pegDiscovery');assert.equal(out.state.pegPreview.stocks.length,100);
 out=engine.advance(out.state,response({manifestCommit:'c'.repeat(40)}),now);out=committed(out);
 assert.equal(out.state.stage,'dispatch');assert.equal(out.op.body.inputs.source_mode,'finalize_peg');assert.equal(out.op.body.inputs.prepare_run_id,'123');assert.equal(out.op.body.inputs.candidate_sha256,'b'.repeat(64));assert.equal(out.op.body.inputs.search_manifest_commit,'c'.repeat(40));
});
test('ambiguous final dispatch gets one durable retry only after exact-run reconciliation',()=>{
 const pinned={...base,stage:'dispatch',dispatchIntent:true,dispatchStartedAt:now,pegFinalReady:true,pegPrepareRunId:'123',pegPrepareRunAttempt:1,pegPrepareHeadSha:run.head_sha,pegCandidateSha256:preview.candidateSha256,pegManifestCommit:'c'.repeat(40)};
 let out=engine.advance(pinned,{statusCode:503,error:true},now);
 assert.equal(out.state.stage,'checkpoint');assert.equal(out.state.nextStage,'findRun');
 const ambiguous=JSON.parse(Buffer.from(out.op.body.content,'base64').toString());assert.equal(ambiguous.dispatchAmbiguousStatus,503);
 out=committed(out);assert.equal(out.state.stage,'findRun');assert.equal(out.op.method,'GET');
 out=engine.advance(out.state,response({workflow_runs:[]}),now+5*60000+1);
 assert.equal(out.state.stage,'checkpoint');assert.equal(out.state.nextStage,'findRun');
 const saved=JSON.parse(Buffer.from(out.op.body.content,'base64').toString());
 assert.equal(saved.pegFinalDispatchRetryCount,1);assert.equal(saved.pegFinalDispatchRetryReady,true);
 out=committed(out);assert.equal(out.op.method,'GET');
 out=engine.advance(out.state,response({workflow_runs:[]}),now+5*60000+2000);
 assert.equal(out.state.stage,'checkpoint');assert.equal(out.state.nextStage,'dispatch');
 out=committed(out);assert.equal(out.state.stage,'dispatch');assert.equal(out.op.body.inputs.source_mode,'finalize_peg');
 const retry=engine.advance(out.state,{statusCode:503,error:true},now+5*60000+3000);
 assert.equal(retry.state.stage,'checkpoint');assert.equal(retry.state.nextStage,'findRun');
 const reconciled=committed(retry);
 const exhausted=engine.advance({...reconciled.state,dispatchStartedAt:now-10*60000},response({workflow_runs:[]}),now+5*60000+4000);
 assert.equal(exhausted.state.errorCategory,'dispatch_run_not_found');
});
test('exact finalized run found during retry reconciliation is adopted without another POST',()=>{
 const pinned={...base,stage:'findRun',dispatchIntent:true,dispatchStartedAt:now-6*60000,pegFinalReady:true,pegPrepareRunId:'123',pegPrepareRunAttempt:1,pegPrepareHeadSha:run.head_sha,pegCandidateSha256:preview.candidateSha256,pegManifestCommit:'c'.repeat(40),pegFinalDispatchRetryCount:1,pegFinalDispatchRetryReady:true};
 const finalized={...run,id:124,display_title:'Daily screening | test-1 | 2026-11-03'};
 const out=engine.advance(pinned,response({workflow_runs:[finalized]}),now);
 assert.equal(out.state.nextStage,'pollRun');assert.equal(out.state.actionsRunId,'124');
});
test('retry authorization waits for every populated Actions run page',()=>{
 const pinned={...base,stage:'findRun',dispatchIntent:true,dispatchStartedAt:now-6*60000,runPage:1,pegFinalReady:true,pegPrepareRunId:'123',pegPrepareRunAttempt:1,pegPrepareHeadSha:run.head_sha,pegCandidateSha256:preview.candidateSha256,pegManifestCommit:'c'.repeat(40),pegFinalDispatchRetryCount:1,pegFinalDispatchRetryReady:true};
 const page=Array.from({length:100},(_,i)=>({...run,id:1000+i,display_title:`unrelated-${i}`}));
 const first=engine.advance(pinned,response({workflow_runs:page}),now);
 assert.equal(first.state.stage,'findRun');assert.equal(first.state.runPage,2);assert.match(first.op.url,/page=2/);
 const final=engine.advance(first.state,response({workflow_runs:[]}),now);
 assert.equal(final.state.stage,'checkpoint');assert.equal(final.state.nextStage,'dispatch');
});
test('released PEG dispatch failure resumes by exact-run lookup with pinned lineage',()=>{
 const pinned={...base,stage:'done',released:true,errorCategory:'dispatch_run_not_found',dispatchIntent:true,dispatchStartedAt:now-6*60000,pegFinalReady:true,pegPrepareRunId:'123',pegPrepareRunAttempt:1,pegPrepareHeadSha:run.head_sha,pegCandidateSha256:preview.candidateSha256,pegManifestCommit:'c'.repeat(40),pegFinalDispatchRetryCount:0};
 const incoming={...base,stage:'state',isOpen:true,owner:'701'};
 let out=engine.advance(incoming,response({sha:'state-sha',content:Buffer.from(JSON.stringify(pinned)).toString('base64')}),now);
 assert.equal(out.state.nextStage,'findRun');
 out=committed(out);assert.equal(out.op.method,'GET');assert.match(out.op.url,/actions\/workflows\/daily.yml\/runs/);
 assert.equal(out.state.pegFinalReady,true);assert.equal(out.state.pegPrepareRunId,'123');assert.equal(out.state.pegManifestCommit,'c'.repeat(40));
});
test('operator-corrected finalized PEG state dispatches only after exact-run lookup',()=>{
 const state={...base,stage:'findRun',dispatchIntent:false,pegFinalReady:true,pegPrepareRunId:'123',pegPrepareRunAttempt:1,pegPrepareHeadSha:run.head_sha,pegCandidateSha256:preview.candidateSha256,pegManifestCommit:'c'.repeat(40)};
 const out=engine.advance(state,response({workflow_runs:[]}),now);
 assert.equal(out.state.stage,'checkpoint');assert.equal(out.state.nextStage,'dispatch');
 const saved=JSON.parse(Buffer.from(out.op.body.content,'base64').toString());assert.equal(saved.dispatchIntent,true);assert.equal(saved.pegFinalReady,true);
});
test('rejects mismatched prepare artifact, preview or manifest',()=>{
 const state={...base,stage:'pegArtifactList',pegPrepareRunId:'123',pegPrepareRunAttempt:1,pegPrepareHeadSha:run.head_sha};
 const bad=engine.advance(state,response({total_count:1,artifacts:[{...artifact,workflow_run:{...artifact.workflow_run,id:124}}]}),now);
 assert.equal(bad.state.errorCategory,'peg_candidate_artifact');
 const badDigest=engine.advance(state,response({total_count:1,artifacts:[{...artifact,digest:'sha256:bad'}]}),now);assert.equal(badDigest.state.errorCategory,'peg_candidate_artifact');
 const oversized=engine.advance(state,response({total_count:1,artifacts:[{...artifact,size_in_bytes:68*1024*1024+1}]}),now);assert.equal(oversized.state.errorCategory,'peg_candidate_artifact');
 const zip=engine.advance({...state,stage:'pegArtifactZip'},response({preview:{...preview,requestId:'other'},candidateSha256:preview.candidateSha256}),now);
 assert.equal(zip.state.errorCategory,'peg_candidate_lineage');
 const discover=engine.advance({...state,stage:'pegDiscovery',pegPreview:preview,pegCandidateSha256:preview.candidateSha256},response({manifestCommit:'bad'}),now);
 assert.equal(discover.state.errorCategory,'peg_manifest_commit');
});

test('prepare run rejects foreign repository and duplicate matches',()=>{
 const state={...base,stage:'pegFindPrepare',pegPrepareIntent:true,pegPrepareStartedAt:now};
 const foreign=engine.advance(state,response({workflow_runs:[{...run,head_repository:{id:1}}]}),now);assert.equal(foreign.state.errorCategory,'peg_prepare_run_lineage');
 const duplicate=engine.advance(state,response({workflow_runs:[run,run]}),now);assert.equal(duplicate.state.errorCategory,'peg_ambiguous_prepare_runs');
 const pending=engine.advance(state,response({workflow_runs:[]}),now);assert.equal(pending.state.stage,'pegFindPrepare');assert.equal(pending.delaySeconds,15);assert.equal(pending.op.method,'GET');
});
test('legacy direct publish checkpoint fails closed into prepare stage',()=>{
 const state={...base,stage:'checkpoint',nextStage:'dispatch',dispatchIntent:true};
 const out=engine.advance(state,response({content:{sha:'new'}}),now);
 assert.equal(out.state.stage,'checkpoint');assert.equal(out.state.nextStage,'pegFindPrepare');assert.equal(out.state.dispatchIntent,false);
});
test('retry with a new request clears old candidate lineage',()=>{
 const state={...base,stage:'failedRunArtifacts',automaticRetryCandidateStep:'Fetch authoritative exchange calendar',actionsRunId:'789',failedRunHeadSha:'e'.repeat(40),failedRunAttempt:1,pegFinalReady:true,pegPrepareRunId:'123',pegCandidateSha256:'b'.repeat(64),pegPreview:preview,pegManifestCommit:'c'.repeat(40)};
 const out=engine.advance(state,response({total_count:0,artifacts:[]}),now);
 assert.equal(out.state.nextStage,'findRun');assert.equal(out.state.pegFinalReady,undefined);assert.equal(out.state.pegPreview,undefined);assert.equal(out.state.pegPrepareRunId,undefined);
});
test('eligible scheduled source failure inspects exact prepare job and artifacts before one new request',()=>{
 const state={...base,stage:'pegPollPrepare',automaticRequestId:true,pegPrepareRunId:'123',pegPrepareHeadSha:run.head_sha,pegPrepareIntent:true};
 let out=engine.advance(state,response({...run,conclusion:'failure'}),now);assert.equal(out.state.nextStage,'pegFailedJobs');out=committed(out);assert.match(out.op.url,/actions\/runs\/123\/jobs/);
 const step={name:'Fetch official institutional universe',status:'completed',conclusion:'failure'};
 const jobs={total_count:2,jobs:[{name:'snapshot',run_id:123,run_attempt:1,head_sha:run.head_sha,status:'completed',conclusion:'failure',steps:[step]},{name:'institutional_probe',run_id:123,run_attempt:1,head_sha:run.head_sha,status:'completed',conclusion:'skipped'}]};
 out=engine.advance(out.state,response(jobs),now);assert.equal(out.state.nextStage,'pegFailedArtifacts');out=committed(out);assert.match(out.op.url,/actions\/runs\/123\/artifacts/);
 out=engine.advance(out.state,response({total_count:0,artifacts:[]}),now);assert.equal(out.state.nextStage,'findRun');assert.equal(out.state.requestId,'test-1:retry1');assert.equal(out.state.pegPrepareRunId,undefined);
});
test('manual or non-source prepare failure never retries',()=>{
 const state={...base,runKind:'manual',stage:'pegPollPrepare',automaticRequestId:true,pegPrepareRunId:'123',pegPrepareHeadSha:run.head_sha};
 const out=engine.advance(state,response({...run,conclusion:'failure'}),now);assert.equal(out.state.errorCategory,'peg_prepare_failed');assert.equal(out.state.nextStage,'done');
});
test('expired owner resumes saved prepare intent without redispatch and resumes verified preview',()=>{
 const incoming={...base,stage:'state',owner:'701',isOpen:true};
 for(const storedStage of ['pegDispatchPrepare','pegDiscovery']) {
  const old={...base,owner:'700',stage:storedStage,deadline:now-1,operationDeadline:now+3600000,released:false,pegPrepareIntent:true,pegPrepareStartedAt:now-1000,pegPrepareRunId:'123',pegPrepareRunAttempt:1,pegPrepareHeadSha:run.head_sha,pegPreview:preview,pegCandidateSha256:preview.candidateSha256};
  const out=engine.advance(incoming,response({sha:'stored',content:Buffer.from(JSON.stringify(old)).toString('base64')}),now);
  assert.equal(out.state.nextStage,storedStage==='pegDispatchPrepare'?'pegFindPrepare':'pegDiscovery');
  const resumed=committed(out);assert.equal(resumed.state.owner,'701');assert.equal(resumed.state.stage,storedStage==='pegDispatchPrepare'?'pegFindPrepare':'pegDiscovery');
  if(storedStage==='pegDispatchPrepare')assert.equal(resumed.op.method,'GET');else assert.equal(resumed.state.pegPreview.requestId,base.requestId);
 }
});
test('manifest checkpoint drops transient preview but retains pinned candidate lineage',()=>{
 const state={...base,stage:'pegDiscovery',pegPreview:preview,pegPrepareRunId:'123',pegPrepareRunAttempt:1,pegPrepareHeadSha:run.head_sha,pegCandidateSha256:preview.candidateSha256};
 const out=engine.advance(state,response({manifestCommit:'c'.repeat(40)}),now);
 const stored=JSON.parse(Buffer.from(out.op.body.content,'base64').toString('utf8'));
 assert.equal(stored.pegPreview,undefined);assert.equal(stored.pegPrepareRunId,'123');assert.equal(stored.pegPrepareRunAttempt,1);assert.equal(stored.pegCandidateSha256,preview.candidateSha256);assert.equal(stored.pegManifestCommit,'c'.repeat(40));
});
test('checkpoint size limit permits 900 KiB and fails closed above it',()=>{
 const state={...base,stage:'pegDiscovery',pegPreview:preview,pegPrepareRunId:'123',pegPrepareRunAttempt:1,pegPrepareHeadSha:run.head_sha,pegCandidateSha256:preview.candidateSha256,padding:''};
 const baseline=engine.advance(state,response({manifestCommit:'c'.repeat(40)}),now);
 const used=Buffer.from(baseline.op.body.content,'base64').length;
 const limit=900*1024;
 const atLimit=engine.advance({...state,padding:'x'.repeat(limit-used)},response({manifestCommit:'c'.repeat(40)}),now);
 assert.equal(Buffer.from(atLimit.op.body.content,'base64').length,limit);
 const oversized=engine.advance({...state,padding:'x'.repeat(limit-used+1)},response({manifestCommit:'c'.repeat(40)}),now);
 assert.equal(oversized.state.stage,'done');assert.equal(oversized.state.errorCategory,'checkpoint_too_large');assert.equal(oversized.op,null);assert.match(oversized.state.errorMessage,/no checkpoint was written/i);
});
