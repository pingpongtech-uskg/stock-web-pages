// Pure dispatcher transitions. Source acquisition and serialized state custody belong to ownership.yml.
const {calendarOpen,latestCompletedSession}=require('./engine.cjs');
const {sha256}=require('./runtime.cjs');
const OWNERSHIP_REPO='https://api.github.com/repos/pingpongtech-uskg/stock-web-pages';
function ownershipResult(state,op=null,delaySeconds=0){return {state,op,route:op?(op.method==='POST'?'dispatch':op.method==='PUT'?'write':'read'):'done',delaySeconds};}
function ownershipRequest(state,stage,url,body=null,delaySeconds=0){return ownershipResult({...state,stage},{method:body?'POST':'GET',url,body},delaySeconds);}
function ownershipDone(state,errorCategory='',status='failed'){return ownershipResult({...state,stage:'done',status,errorCategory});}
function ownershipStart(input,now=Date.now()) {
  if(!/^\d{1,24}$/.test(String(input.owner||'')))throw Error('ownership_owner');
  if(!['manual','scheduled'].includes(input.run_kind))throw Error('ownership_run_kind');
  const local=new Date(now+8*3600000),today=local.toISOString().slice(0,10),manual=input.run_kind==='manual';
  const explicit=input.verified_market_date;
  if(manual&&(!/^\d{4}-\d{2}-\d{2}$/.test(explicit||'')||!Number.isFinite(Date.parse(explicit+'T00:00:00Z'))||new Date(explicit+'T00:00:00Z').toISOString().slice(0,10)!==explicit||explicit>today))throw Error('ownership_verified_market_date');
  const minutes=local.getUTCHours()*60+local.getUTCMinutes();
  if(!manual&&([0,6].includes(local.getUTCDay())||minutes<1020||minutes>=1065))throw Error('ownership_schedule_slot');
  if(manual&&!/^[a-zA-Z0-9_.-]{1,64}$/.test(input.manual_batch_id||''))throw Error('ownership_manual_batch_id');
  const slot=manual?'manual:'+input.manual_batch_id:minutes<1035?'1700':minutes<1050?'1715':'1730';
  return ownershipRequest({runKind:input.run_kind,explicit,slot,startedAt:now,deadline:now+15*60000,status:'pending',owner:String(input.owner)},'calendar','https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule');
}
function ownershipFind(state,delay=0){return ownershipRequest(state,'findRun',`${OWNERSHIP_REPO}/actions/workflows/ownership.yml/runs?event=workflow_dispatch&per_page=100&page=${state.page||1}`,null,delay);}
function ownershipIntentUrl(state){return `${OWNERSHIP_REPO}/contents/operations/ownership-dispatch/${state.marketDate.slice(0,4)}/${sha256(state.requestId)}.json`;}
function ownershipIntentRead(state,stage='intentRead'){return ownershipRequest(state,stage,ownershipIntentUrl(state)+'?ref=n8n-state');}
function ownershipIntentBody(body,state,now){
  if(body?.encoding!=='base64'||typeof body.content!=='string'||body.content.length>8000)throw Error('ownership_intent_schema');
  const intent=JSON.parse(Buffer.from(body.content,'base64').toString('utf8'));
  if(intent.schemaVersion!=='ownership-dispatch-intent-v1'||intent.marketDate!==state.marketDate||intent.requestId!==state.requestId||intent.workflow!=='ownership.yml'||intent.ref!=='main'||!/^[a-f0-9]{40}$/.test(intent.sourceCommit||'')||!/^\d{1,24}$/.test(intent.owner||'')||!Number.isSafeInteger(intent.createdAt)||intent.createdAt>now||intent.dispatchIntent!==true)throw Error('ownership_intent_lineage');
  return intent;
}
function ownershipDispatch(state){return ownershipRequest(state,'dispatch',`${OWNERSHIP_REPO}/actions/workflows/ownership.yml/dispatches`,{ref:'main',inputs:{request_id:state.requestId,market_date:state.marketDate}});}
function ownershipValidateRun(run,state){
  if(run.display_title!==`Ownership update | ${state.requestId} | ${state.marketDate}`||run.event!=='workflow_dispatch'||run.head_branch!=='main'||!['.github/workflows/ownership.yml','.github/workflows/ownership.yml@main','.github/workflows/ownership.yml@refs/heads/main'].includes(run.path)||run.head_sha!==state.sourceCommit||!/^[a-f0-9]{40}$/.test(run.head_sha||'')||!/^\d{1,24}$/.test(String(run.id)))throw Error('ownership_run_lineage');
  if(state.actionsRunId&&(String(run.id)!==state.actionsRunId||run.head_sha!==state.runHeadSha))throw Error('ownership_run_lineage');
}
function ownershipPoll(state){return ownershipRequest(state,'pollRun',`${OWNERSHIP_REPO}/actions/runs/${state.actionsRunId}`,null,15);}
function ownershipAdvance(state,response,now=Date.now()) {
  if(now>=state.deadline)return ownershipDone(state,'ownership_deadline');
  if(state.stage==='done')return ownershipResult(state);
  if(state.stage==='dispatch')return ownershipFind({...state,dispatchIntent:true,dispatchAt:state.dispatchAt||now,page:1,matches:[]},15);
  if(state.stage==='intentWrite')return ownershipIntentRead(state,'intentVerify');
  if(state.stage==='intentRead'&&Number(response?.statusCode)===404)return ownershipFind(state);
  if(Number(response?.statusCode??200)<200||Number(response?.statusCode??200)>=300)return ownershipDone(state,'github_read_failed');
  let body=response.body??response.data;if(typeof body==='string')body=JSON.parse(body);
  if(state.stage==='calendar') {
    if(state.runKind==='scheduled'&&!calendarOpen(body,new Date(now+8*3600000).toISOString().slice(0,10)))return ownershipDone(state,'','skipped_non_trading');
    const marketDate=state.runKind==='manual'?state.explicit:latestCompletedSession(body,now);
    if(!calendarOpen(body,marketDate))throw Error('ownership_verified_market_date_closed');
    return ownershipRequest({...state,marketDate,requestId:`ownership:${marketDate.replaceAll('-','')}:${state.slot}`,page:1,matches:[]},'mainRef',OWNERSHIP_REPO+'/git/ref/heads/main');
  }
  if(state.stage==='mainRef') {
    if(!/^[a-f0-9]{40}$/.test(body?.object?.sha||''))throw Error('ownership_main_ref');
    return ownershipIntentRead({...state,sourceCommit:body.object.sha});
  }
  if(state.stage==='intentRead'||state.stage==='intentVerify') {
    const intent=ownershipIntentBody(body,state,now);
    if(state.stage==='intentVerify') {
      if(intent.owner!==state.owner||JSON.stringify(intent)!==JSON.stringify(state.intent))return ownershipDone(state,'ownership_intent_claim_lost');
      return ownershipDispatch({...state,dispatchIntent:true,dispatchAt:intent.createdAt});
    }
    return ownershipFind({...state,sourceCommit:intent.sourceCommit,dispatchIntent:true,dispatchAt:intent.createdAt,page:1,matches:[]});
  }
  if(state.stage==='findRun') {
    if(!Array.isArray(body?.workflow_runs)||body.workflow_runs.length>100)throw Error('ownership_runs_schema');
    const matches=[...(state.matches||[]),...body.workflow_runs.filter(run=>run.display_title===`Ownership update | ${state.requestId} | ${state.marketDate}`)];
    if(matches.length>1)throw Error('ownership_ambiguous_runs');
    if(body.workflow_runs.length===100){if(state.page>=10)throw Error('ownership_scan_limit');return ownershipFind({...state,page:state.page+1,matches});}
    if(matches.length){ownershipValidateRun(matches[0],state);return ownershipPoll({...state,actionsRunId:String(matches[0].id),runHeadSha:matches[0].head_sha,matches:[]});}
    if(state.dispatchIntent){if(now-state.dispatchAt>=5*60000)return ownershipDone(state,'dispatch_run_not_found');return ownershipFind({...state,page:1,matches:[]},15);}
    const intent={schemaVersion:'ownership-dispatch-intent-v1',marketDate:state.marketDate,requestId:state.requestId,workflow:'ownership.yml',ref:'main',sourceCommit:state.sourceCommit,owner:state.owner,createdAt:now,dispatchIntent:true};
    return ownershipResult({...state,stage:'intentWrite',intent},{method:'PUT',url:ownershipIntentUrl(state),body:{message:'[CF-Pages-Skip] chore: ownership dispatch intent',branch:'n8n-state',content:Buffer.from(JSON.stringify(intent)).toString('base64')}});
  }
  if(state.stage==='pollRun') {
    ownershipValidateRun(body,state);
    if(body.status==='completed')return ownershipDone(state,body.conclusion==='success'?'':String(body.conclusion||'unknown'),body.conclusion==='success'?'acquisition_job_succeeded':'acquisition_job_failed');
    if(!['queued','in_progress','waiting','pending','requested'].includes(body.status))throw Error('ownership_run_status');
    return ownershipPoll(state);
  }
  throw Error('ownership_stage');
}
if(typeof module!=='undefined')module.exports={ownershipStart,ownershipAdvance};
