'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {validatePreview,bindManifest}=require('./peg-candidate-contract.cjs');
const input={requestId:'stockscreener:20261103:v1',marketDate:'2026-11-03',prepareRunId:'123',prepareRunAttempt:1,sourceGitCommit:'a'.repeat(40),candidateSha256:'b'.repeat(64)};
const preview={...input,stocks:Array.from({length:100},(_,i)=>({code:String(1000+i),name:'Company '+i,pegReview:{status:i === 0 ? 'needs_review' : 'ok'},currentPeriod:'2026Q2'}))};
test('binds search results to exact frozen candidate lineage',()=>{
 const safe=validatePreview(preview,input);
 const manifest=bindManifest({marketDate:input.marketDate,requestId:input.requestId,stocks:[{code:'1000',legalName:'Company',officialDomains:['example.com'],results:[]}]},safe);
 for(const k of ['requestId','marketDate','prepareRunId','prepareRunAttempt','candidateSha256'])assert.equal(manifest[k],input[k]);
});
test('rejects mismatched lineage, duplicate codes and out-of-candidate results',()=>{
 assert.throws(()=>validatePreview({...preview,candidateSha256:'c'.repeat(64)},input),/candidate_lineage/);
 assert.throws(()=>validatePreview({...preview,stocks:[...preview.stocks.slice(0,99),preview.stocks[0]]},input),/candidate_stocks/);
 assert.throws(()=>bindManifest({marketDate:input.marketDate,requestId:input.requestId,stocks:[{code:'9999',results:[]}]},validatePreview(preview,input)),/manifest_stocks/);
});
test('prepare run and artifact must match exact trusted identity',()=>{
 const {validatePrepareRun,selectCandidateArtifact}=require('./peg-candidate-contract.cjs');
 const run={id:123,run_attempt:1,display_title:`Daily PEG prepare | ${input.requestId} | ${input.marketDate}`,event:'workflow_dispatch',head_branch:'main',path:'.github/workflows/daily.yml',head_sha:input.sourceGitCommit,status:'completed',conclusion:'success'};
 validatePrepareRun(run,input);
 const artifact={id:456,name:'peg-candidate-123-1',expired:false,workflow_run:{id:123,head_sha:input.sourceGitCommit,repository_id:1273106108,head_repository_id:1273106108}};
 assert.equal(selectCandidateArtifact({total_count:1,artifacts:[artifact]},input).id,456);
 assert.throws(()=>validatePrepareRun({...run,head_sha:'c'.repeat(40)},input),/prepare_run_lineage/);
 assert.throws(()=>selectCandidateArtifact({total_count:1,artifacts:[{...artifact,workflow_run:{...artifact.workflow_run,id:124}}]},input),/candidate_artifact/);
 assert.throws(()=>selectCandidateArtifact({total_count:2,artifacts:[artifact,artifact]},input),/candidate_artifact/);
});
test('manifest includes available stocks flagged for discovery without changing PEG status',()=>{
 const altered={...preview,stocks:preview.stocks.map((s,i)=>i===1?{...s,pegDiscoveryRequired:true}:s)};
 const safe=validatePreview(altered,input);
 const stocks=[0,1].map(i=>({code:String(1000+i),legalName:'Company',officialDomains:['example.com'],results:[]}));
 assert.equal(bindManifest({marketDate:input.marketDate,requestId:input.requestId,stocks},safe).stocks.length,2);
 assert.equal(safe.stocks[1].pegReview.status,'ok');
});
