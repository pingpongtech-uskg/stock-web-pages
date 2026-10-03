// Temporary operator helper. Pure transitions; no network, credentials, Notion or daily CAS.
const {sourceValidateArtifact}=typeof module!=='undefined'?require('./source-probe-artifact.cjs'):{sourceValidateArtifact:globalThis.sourceValidateArtifact};
const SOURCE_REPO='https://api.github.com/repos/pingpongtech-uskg/stock-web-pages';
const SOURCE_BRANCH='fix/n8n-daily-screening';
const SOURCE_SHA=/^[a-f0-9]{40}$/;
function sourceResult(state,op,delaySeconds=0.5){return {state:{...state,op},op,route:op?.route||'done',delaySeconds,ledgerRequired:state.stage==='done'};}
function sourceRequest(state,stage,method,path,body,delaySeconds=0.5){return sourceResult({...state,stage},{route:'github',method,url:SOURCE_REPO+path,body:body||{}},delaySeconds);}
function sourceDone(state,outcome,errorCategory){return sourceResult({...state,stage:'done',outcome,...(errorCategory?{errorCategory}:{})},null);}
function sourceOutcome(state){return {operation:state.plan.mode,stage:state.stage,outcome:state.outcome||'in_progress',requestId:state.plan.requestId||'',marketDate:state.plan.marketDate||'',sourceGitCommit:state.plan.probeHeadSha||state.plan.targetSha||'',actionsRunId:state.runId||'',dispatchIntent:!!state.dispatchIntent,errorCategory:state.errorCategory||'',...(state.probeSummary?{probeSummary:state.probeSummary,artifactByteHashes:state.artifactByteHashes,runConclusion:state.runConclusion}:{})};}
function sourceStart(plan,now=Date.now()){
 if(!['inspect','prepare_feature','promote_main','dispatch_probe','read_probe'].includes(plan.mode))throw Error('source_input');
 if(['prepare_feature','promote_main'].includes(plan.mode)&&![plan.baseSha,plan.targetSha,plan.targetTreeSha].every(value=>SOURCE_SHA.test(value||'')))throw Error('source_input');
 if(plan.mode==='prepare_feature'){
  if(!SOURCE_SHA.test(plan.featureBaseSha||'')||!SOURCE_SHA.test(plan.baseTreeSha||'')||!Array.isArray(plan.blobs)||!Array.isArray(plan.treeEntries)||plan.blobs.length>100||plan.treeEntries.length>100||Buffer.byteLength(JSON.stringify(plan),'utf8')>1500000)throw Error('source_manifest');
  if(plan.blobs.some(item=>!SOURCE_SHA.test(item.sha)||!item.content||!/^[A-Za-z0-9+/]*={0,2}$/.test(item.content))||plan.treeEntries.some(item=>typeof item.path!=='string'||item.path.startsWith('/')||item.path.split('/').some(part=>!part||part==='..'||part==='.')||item.type!=='blob'||item.mode!=='100644'||(item.sha!==null&&!SOURCE_SHA.test(item.sha))))throw Error('source_manifest');
  if(plan.commit?.tree!==plan.targetTreeSha||plan.commit?.parents?.length!==1||plan.commit.parents[0]!==plan.baseSha||typeof plan.commit.message!=='string'||!plan.commit.author||!plan.commit.committer)throw Error('source_manifest');
 }
 if(plan.mode==='promote_main'&&!/^\d{1,24}$/.test(plan.ciRunId||''))throw Error('source_input');
 if(['dispatch_probe','read_probe'].includes(plan.mode)&&(!SOURCE_SHA.test(plan.probeHeadSha||'')||!/^\d{4}-\d{2}-\d{2}$/.test(plan.marketDate||'')||new Date(plan.marketDate+'T00:00:00Z').toISOString().slice(0,10)!==plan.marketDate||!/^institutional-probe:[A-Za-z0-9_.:-]{1,140}$/.test(plan.requestId||'')))throw Error('source_input');
 if(plan.mode==='read_probe'&&!/^\d{1,24}$/.test(plan.runId||''))throw Error('source_input');
 return sourceRequest({plan,startedAt:now,deadline:now+20*60000,blobIndex:0},'main','GET','/git/ref/heads/main');
}
function sourceFindRuns(state,delaySeconds=0.5){return sourceRequest(state,'findRun','GET',`/actions/workflows/daily.yml/runs?event=workflow_dispatch&per_page=100&page=${state.runPage||1}`,null,delaySeconds);}
function sourceTrustedRun(run,state){return String(run.id)===String(state.runId||run.id)&&run.workflow_id===state.workflowId&&run.head_sha===state.plan.probeHeadSha&&run.head_branch==='main'&&run.event==='workflow_dispatch'&&run.head_repository?.full_name==='pingpongtech-uskg/stock-web-pages'&&run.display_title===`Daily screening | ${state.plan.requestId} | ${state.plan.marketDate}`;}
function sourceAdvance(state,response,now=Date.now()){
 if(now>=state.deadline)return sourceDone(state,'failed','source_deadline');
 const status=Number(response.statusCode||0);
 if(state.stage==='dispatch'&&(status>=500||response.error))return sourceFindRuns({...state,dispatchIntent:true},15);
 if(status<200||status>=300){if(state.stage==='artifactRedirect'&&status===302)return sourceRedirect(state,response.headers);return sourceDone(state,'failed','github_http_'+status);}
 let body=response.body??response.data??{};if(typeof body==='string'){try{body=JSON.parse(body);}catch{return sourceDone(state,'failed','github_response_schema');}}
 try{return sourceAdvanceSuccess(state,body,response,now);}catch(error){return sourceDone(state,'failed',error.message.split(':')[0]);}
}
function sourceAdvanceSuccess(state,body,response,now){
 const plan=state.plan;
 switch(state.stage){
  case 'main':
   if(plan.mode==='inspect')return sourceDone({...state,observedMainSha:body.object?.sha},'inspected');
   if(body.object?.sha!==(['dispatch_probe','read_probe'].includes(plan.mode)?plan.probeHeadSha:plan.baseSha))throw Error('main_changed');
   return sourceRequest(state,['dispatch_probe','read_probe'].includes(plan.mode)?'probeWorkflow':'feature','GET',['dispatch_probe','read_probe'].includes(plan.mode)?'/actions/workflows/daily.yml':'/git/ref/heads/'+SOURCE_BRANCH);
  case 'feature':
   if(plan.mode==='prepare_feature'&&body.object?.sha===plan.targetSha)return sourceDone(state,'feature_verified');
   if(body.object?.sha!==(plan.mode==='prepare_feature'?plan.featureBaseSha:plan.targetSha))throw Error('feature_changed');
   return sourceRequest(state,plan.mode==='prepare_feature'?'baseCommit':'ciWorkflow','GET',plan.mode==='prepare_feature'?'/git/commits/'+plan.baseSha:'/actions/workflows/ci.yml');
  case 'baseCommit':
   if(body.sha!==plan.baseSha||body.tree?.sha!==plan.baseTreeSha)throw Error('base_tree_mismatch');
   return sourceNextBlob(state);
  case 'blob':
   if(body.sha!==plan.blobs[state.blobIndex].sha)throw Error('blob_sha_mismatch');
   return sourceNextBlob({...state,blobIndex:state.blobIndex+1});
  case 'tree':
   if(body.sha!==plan.targetTreeSha)throw Error('tree_sha_mismatch');
   return sourceRequest(state,'commit','POST','/git/commits',plan.commit);
  case 'commit':
   if(body.sha!==plan.targetSha)throw Error('commit_sha_mismatch');
   return sourceRequest(state,'featureRecheck','GET','/git/ref/heads/'+SOURCE_BRANCH);
  case 'featureRecheck':
   if(body.object?.sha!==plan.featureBaseSha)throw Error('feature_changed');
   return sourceRequest(state,'mainRecheck','GET','/git/ref/heads/main');
  case 'ciWorkflow':return sourceRequest({...state,workflowId:body.id},'ciRun','GET','/actions/runs/'+plan.ciRunId);
  case 'ciRun':
   if(body.id!==Number(plan.ciRunId)||body.workflow_id!==state.workflowId||body.head_sha!==plan.targetSha||body.head_branch!==SOURCE_BRANCH||body.event!=='push'||body.status!=='completed'||body.conclusion!=='success'||body.repository?.full_name!=='pingpongtech-uskg/stock-web-pages')throw Error('ci_gate');
   return sourceRequest(state,'targetCommit','GET','/git/commits/'+plan.targetSha);
  case 'targetCommit':
   if(body.sha!==plan.targetSha||body.tree?.sha!==plan.targetTreeSha||body.parents?.length!==1||body.parents[0].sha!==plan.baseSha)throw Error('target_commit_gate');
   return sourceRequest(state,'mainRecheck','GET','/git/ref/heads/main');
  case 'mainRecheck':
   if(body.object?.sha!==plan.baseSha)throw Error('main_changed');
   return sourceRequest(state,plan.mode==='prepare_feature'?'featureWrite':'mainWrite','PATCH','/git/refs/heads/'+(plan.mode==='prepare_feature'?SOURCE_BRANCH:'main'),{sha:plan.targetSha,force:false});
  case 'featureWrite':case 'mainWrite':
   if(body.object?.sha!==plan.targetSha)throw Error('ref_write_mismatch');
   return sourceRequest(state,state.stage==='featureWrite'?'featureVerify':'mainVerify','GET','/git/ref/heads/'+(state.stage==='featureWrite'?SOURCE_BRANCH:'main'));
  case 'featureVerify':case 'mainVerify':
   if(body.object?.sha!==plan.targetSha)throw Error('ref_readback_mismatch');
   return sourceDone(state,state.stage==='featureVerify'?'feature_verified':'main_verified');
  case 'probeWorkflow':
   if(!Number.isInteger(body.id)||body.state&&body.state!=='active')throw Error('workflow_gate');
   return plan.mode==='read_probe'?sourceRequest({...state,workflowId:body.id,runId:plan.runId},'pollRun','GET','/actions/runs/'+plan.runId):sourceFindRuns({...state,workflowId:body.id});
  case 'findRun':{
   if(!Array.isArray(body.workflow_runs))throw Error('actions_schema');
   const matches=[...(state.runMatches||[]),...body.workflow_runs.filter(run=>run.display_title===`Daily screening | ${plan.requestId} | ${plan.marketDate}`)];
   if(matches.length>1)throw Error('ambiguous_probe_runs');
   if(body.workflow_runs.length===100){if((state.runPage||1)>=10)throw Error('actions_scan_limit');return sourceFindRuns({...state,runPage:(state.runPage||1)+1,runMatches:matches});}
   if(matches[0]){if(!sourceTrustedRun(matches[0],state))throw Error('probe_run_lineage');return sourceRequest({...state,runId:String(matches[0].id),runMatches:[]},'pollRun','GET','/actions/runs/'+matches[0].id,null,15);}
   if(state.dispatchIntent){if(now-state.startedAt>=5*60000)throw Error('probe_dispatch_unconfirmed');return sourceFindRuns({...state,runPage:1},15);}
   return {...sourceResult({...state,stage:'dispatch',dispatchIntent:true},{route:'native',method:'POST',url:SOURCE_REPO+'/actions/workflows/daily.yml/dispatches',body:{ref:'main',inputs:{request_id:plan.requestId,market_date:plan.marketDate,source_mode:'institutional_probe'}}}),ledgerRequired:true};
  }
  case 'dispatch':return sourceFindRuns({...state,dispatchIntent:true},15);
  case 'pollRun':
   if(!sourceTrustedRun(body,state))throw Error('probe_run_lineage');
   if(body.status!=='completed')return sourceRequest(state,'pollRun','GET','/actions/runs/'+state.runId,null,15);
   return sourceRequest({...state,runAttempt:body.run_attempt||1,runConclusion:body.conclusion},'artifactList','GET','/actions/runs/'+state.runId+'/artifacts?per_page=100');
  case 'artifactList':{
   if(body.total_count>100||!Array.isArray(body.artifacts))throw Error('artifact_schema');
   const matches=body.artifacts.filter(item=>item.name==='institutional-probe'&&!item.expired);
   if(matches.length!==1)throw Error('probe_artifact_missing_or_ambiguous');const artifact=matches[0];
   if(!Number.isInteger(artifact.id)||artifact.size_in_bytes>3000000||artifact.workflow_run?.id!==Number(state.runId)||artifact.workflow_run?.head_sha!==plan.probeHeadSha)throw Error('probe_artifact_lineage');
   return sourceRequest({...state,artifactId:artifact.id},'artifactRedirect','GET','/actions/artifacts/'+artifact.id+'/zip');
  }
  case 'artifactBytes':{const evidence=sourceValidateArtifact(body,state);return sourceDone({...state,probeSummary:evidence.summary,artifactByteHashes:evidence.byteHashes},'probe_evidence_verified');}
  default:throw Error('source_stage');
 }
}
function sourceNextBlob(state){const plan=state.plan;return state.blobIndex<plan.blobs.length?sourceRequest(state,'blob','POST','/git/blobs',{encoding:'base64',content:plan.blobs[state.blobIndex].content}):sourceRequest(state,'tree','POST','/git/trees',{base_tree:plan.baseTreeSha,tree:plan.treeEntries});}
function sourceRedirect(state,headers){const url=headers?.location||headers?.Location;if(typeof url!=='string'||!/^https:\/\/[a-zA-Z0-9.-]+\.(blob\.core\.windows\.net|actions\.githubusercontent\.com|githubusercontent\.com)\//.test(url))return sourceDone(state,'failed','artifact_storage_origin');return sourceResult({...state,stage:'artifactBytes'},{route:'zip',method:'GET',url});}
if(typeof module!=='undefined')module.exports={sourceStart,sourceAdvance,sourceOutcome};
