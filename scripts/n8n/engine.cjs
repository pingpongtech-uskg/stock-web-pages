// Pure state transitions; all requests execute through n8n credential nodes.
const {validateExport,stockProperties,stockSchema,richText,retrySeconds,sha256}=require('./runtime.cjs');
const {validateLegacyArchive}=require('./legacy.cjs');
const cacheOperation=require('./cache-operation.cjs');
const restoreOperation=require('./cache-restore-operation.cjs');
const REPO='https://api.github.com/repos/pingpongtech-uskg/stock-web-pages';
const REPOSITORY_ID='1273106108';
const ROOT_SOURCE='3ed6fb57-ff38-803d-815a-000b148c6b6e';
const ROOT_DATABASE='3ed6fb57-ff38-8032-97cc-f017b6104300';
const CALENDAR='https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule';
const RETRYABLE_SOURCE_STEPS=new Set(['Fetch authoritative exchange calendar','Fetch official institutional universe','Verify independent requested date against fetched official date']);
const PUBLICATION_STEPS=new Set(['Build lightweight publication fingerprint','Build canonical screening export','Build and validate complete market cache before publication','Publish validated release to main']);
const ROOT_FIELDS={ 'Market Date':{date:{}},'Request ID':{rich_text:{}},'Run ID':{rich_text:{}},'Actions Run ID':{rich_text:{}},'Source Commit':{rich_text:{}},'Payload Hash':{rich_text:{}},'Active Revision':{rich_text:{}},'Screening Status':{rich_text:{}},'Notion Status':{rich_text:{}},'Deploy Status':{rich_text:{}},'Summary':{rich_text:{}},'Selected Count':{number:{}},'Trust Count':{number:{}},'Growth Count':{number:{}},'Low Position Count':{number:{}} };
const OPERATION_FIELDS={'Generated At':{date:{}},'Quality':{rich_text:{}},'Archive Method':{rich_text:{}},'Archive Source Commit':{rich_text:{}},'Expected Count':{number:{}},'Archived Count':{number:{}},'Child Database ID':{rich_text:{}},'Child Data Source ID':{rich_text:{}},'Actions URL':{url:{}},'Archive URL':{url:{}},'Error Summary':{rich_text:{}},'Financial Cutoff':{rich_text:{}},'Coverage':{rich_text:{}},'Formula Versions':{rich_text:{}}};
const ALL_ROOT_FIELDS={...ROOT_FIELDS,...OPERATION_FIELDS,...cacheOperation.CACHE_FIELDS};
function calendarOpen(rows,day) {
  if(!Array.isArray(rows)||!rows.length) throw Error('calendar_empty');
  const dates=rows.map(row=>{
    if(!/^\d{7}$/.test(row.Date)||typeof row.Name!=='string') throw Error('calendar_schema');
    return {...row,iso:`${Number(row.Date.slice(0,3))+1911}-${row.Date.slice(3,5)}-${row.Date.slice(5,7)}`};
  });
  if(dates.some(row=>row.iso.slice(0,4)!==day.slice(0,4))) throw Error('calendar_year');
  if([0,6].includes(new Date(`${day}T00:00:00Z`).getUTCDay())) return false;
  const events=dates.filter(row=>row.iso===day);
  return !events.some(row=>!['開始交易日','最後交易日','國曆新年開始交易日','農曆春節前最後交易日','農曆春節後開始交易日'].includes(row.Name));
}
function latestCompletedSession(rows,now) {
  const local=new Date(now+8*3600000);
  const today=local.toISOString().slice(0,10);
  calendarOpen(rows,today); // Validate the official payload even when today is closed.
  const beforeClose=local.getUTCHours()*60+local.getUTCMinutes()<13*60+30;
  for(let offset=beforeClose?1:0;offset<32;offset++) {
    const day=new Date(Date.parse(today+'T00:00:00Z')-offset*86400000).toISOString().slice(0,10);
    if(day.slice(0,4)!==today.slice(0,4)) throw Error('calendar_year_boundary');
    if(calendarOpen(rows,day)) return day;
  }
  throw Error('completed_session_unavailable');
}
function selectRun(runs,state) {
  const title=`Daily screening | ${state.requestId} | ${state.marketDate}`;
  const matches=runs.filter(run=>run.display_title===title);
  if(matches.length>1) throw Error('ambiguous_actions_runs');
  return matches[0]||null;
}
function retryableFailedRun(state,run) {
  return state.mode==='screen'&&state.runKind==='scheduled'&&state.automaticRequestId===true&&state.automaticRetryCount===undefined&&!state.automaticRetry&&/^[1-9]\d{0,23}$/.test(String(state.actionsRunId||''))&&state.requestId.length<=153&&
    String(run?.id)===String(state.actionsRunId)&&run?.display_title===`Daily screening | ${state.requestId} | ${state.marketDate}`&&
    ['.github/workflows/daily.yml','.github/workflows/daily.yml@main','.github/workflows/daily.yml@refs/heads/main'].includes(run?.path)&&run?.event==='workflow_dispatch'&&run?.head_branch==='main'&&/^[a-f0-9]{40}$/.test(run?.head_sha||'')&&
    Number.isSafeInteger(run?.run_attempt)&&run.run_attempt>0&&run?.status==='completed'&&run?.conclusion==='failure';
}
function retryableSourceFailure(body,state) {
  if(!Array.isArray(body?.jobs)||body.jobs.length!==2||body.total_count!==body.jobs.length) return null;
  const jobs=body.jobs;
  if(jobs.some(job=>String(job?.run_id)!==String(state.actionsRunId)||job?.run_attempt!==state.failedRunAttempt||job?.head_sha!==state.failedRunHeadSha)) return null;
  const probes=jobs.filter(job=>job?.name==='institutional_probe');
  if(probes.length!==1||probes[0].status!=='completed'||probes[0].conclusion!=='skipped') return null;
  const job=jobs.find(candidate=>candidate?.name==='snapshot');
  if(job?.name!=='snapshot'||job.status!=='completed'||job.conclusion!=='failure'||!Array.isArray(job.steps)) return null;
  if(job.steps.some(step=>step?.status!=='completed'||!['success','skipped','failure'].includes(step?.conclusion))) return null;
  const failed=job.steps.filter(step=>step?.conclusion==='failure');
  if(failed.length!==1||!RETRYABLE_SOURCE_STEPS.has(failed[0].name)||failed[0].status!=='completed') return null;
  if(job.steps.some(step=>step?.conclusion&&!['success','skipped','failure'].includes(step.conclusion))) return null;
  if(job.steps.some(step=>PUBLICATION_STEPS.has(step.name)&&step.conclusion==='success')) return null;
  return failed[0].name;
}
function retryArtifactsAbsent(body,state) {
  if(!Array.isArray(body?.artifacts)||!Number.isSafeInteger(body.total_count)||body.total_count!==body.artifacts.length||body.total_count>100) return false;
  const expectedNames=new Set([`market-source-checkpoint-${state.failedRunAttempt}`,`finmind-checkpoint-${state.failedRunAttempt}`]);
  const seen=new Set();
  for(const artifact of body.artifacts) {
    const artifactId=typeof artifact?.id==='number'?artifact.id:typeof artifact?.id==='string'&&/^[1-9]\d{0,19}$/.test(artifact.id)?Number(artifact.id):NaN;
    if(!artifact||typeof artifact!=='object'||Array.isArray(artifact)||!Number.isSafeInteger(artifactId)||artifactId<1||
      typeof artifact.name!=='string'||!expectedNames.has(artifact.name)||seen.has(artifact.name)||artifact.expired!==false) return false;
    const run=artifact.workflow_run;
    if(!run||typeof run!=='object'||String(run.id)!==String(state.actionsRunId)||run.head_sha!==state.failedRunHeadSha||
      String(run.repository_id)!==REPOSITORY_ID||String(run.head_repository_id)!==REPOSITORY_ID||
      (run.head_branch!==undefined&&run.head_branch!=='main')||(run.run_attempt!==undefined&&run.run_attempt!==state.failedRunAttempt)||
      (run.event!==undefined&&run.event!=='workflow_dispatch')) return false;
    seen.add(artifact.name);
  }
  return true;
}
function failedRun(state,conclusion) {
  return checkpoint({...state,screeningStatus:'failed',recordFailure:true,errorCategory:'screening_failed',errorMessage:String(conclusion)},'rootSchema');
}
function result(state,op,delaySeconds=0.5) {
  return {state:{...state,op},op,route:op?.target||'done',delaySeconds,ledgerRequired:['calendar','done'].includes(state.stage)};
}
function request(state,stage,target,method,url,body,delaySeconds=0.5) {
  return result({...state,stage},{target,method,url,body:body||{}},delaySeconds);
}
function done(state) {return result({...state,stage:'done'},null,0.5);}
function durable(state) {
  const {op,payload,rawExport,archiveRows,pendingStocks,children,runMatches,...rest}=state;
  return restoreOperation.restoreDurable(cacheOperation.cacheDurable(rest));
}
function contents(state) {return `${REPO}/contents/operations/days/${state.marketDate}.json`;}
function archiveContents(state,stage,path){return request(state,stage,'github','GET',`${REPO}/contents/public${path}?ref=${state.archiveCommit}`);}
function contentBytes(body){if(body.encoding!=='base64'||typeof body.content!=='string'||body.size>3000000)throw Error('archive_contents_schema');return Buffer.from(body.content,'base64').toString('utf8');}
function checkpoint(state,nextStage,now=Date.now()) {
  const prepared=nextStage==='dispatch'?{...state,dispatchStartedAt:now}:state;
  const saved={...durable(prepared),stage:nextStage};
  const body={message:`[CF-Pages-Skip] chore: checkpoint Stockscreener ${prepared.marketDate}`,branch:'n8n-state',content:Buffer.from(JSON.stringify(saved)).toString('base64'),...(prepared.lockSha?{sha:prepared.lockSha}:{})};
  return request({...prepared,nextStage},'checkpoint','github','PUT',contents(prepared),body);
}
function fail(state,category,message) {
  const updated={...state,...(state.op?.target==='notion'?{notionStatus:'failed'}:{}),errorCategory:category,errorMessage:String(message||category).slice(0,1000)};
  if(!state.lockSha||category==='writer_busy'||category==='writer_deadline'||category==='writer_conflict') return done(updated);
  return checkpoint({...updated,released:true},'done');
}
function findDaily(state) {return request(state,'findDaily','notion','POST',`https://api.notion.com/v1/data_sources/${ROOT_SOURCE}/query`,{filter:{property:'名稱',title:{equals:state.marketDate.replaceAll('-','')}},page_size:100});}
function findDatabase(state) {return request(state,'findDatabase','notion','GET',`https://api.notion.com/v1/blocks/${state.pageId}/children?page_size=100${state.cursor?'&start_cursor='+encodeURIComponent(state.cursor):''}`);}
function queryRows(state,stage='queryRows') {return request(state,stage,'notion','POST',`https://api.notion.com/v1/data_sources/${state.dataSourceId}/query`,{filter:{property:'Payload Hash',rich_text:{equals:state.payload.payloadHash}},page_size:100,...(state.cursor?{start_cursor:state.cursor}:{})});}
function findRuns(state,delay=0.5) {return request(state,'findRun','github','GET',`${REPO}/actions/workflows/daily.yml/runs?event=workflow_dispatch&per_page=100&page=${state.runPage||1}`,null,delay);}
function rootProperties(state,status) {
  const payload=state.payload;
  if(!payload) return {'Market Date':{date:{start:state.marketDate}},'Request ID':{rich_text:richText(state.requestId)},'Actions Run ID':{rich_text:richText(state.actionsRunId||'')},'Actions URL':{url:state.actionsRunId?`https://github.com/pingpongtech-uskg/stock-web-pages/actions/runs/${state.actionsRunId}`:null},'Screening Status':{rich_text:richText('failed')},'Notion Status':{rich_text:richText('failure_metadata')},'Error Summary':{rich_text:richText(`${state.errorCategory||'screening_failed'}: ${state.errorMessage||'Screening failed; no child stock database was created.'}`)}};
  return {'Market Date':{date:{start:state.marketDate}},'Request ID':{rich_text:richText(state.requestId)},'Run ID':{rich_text:richText(payload.runId)},'Actions Run ID':{rich_text:richText(state.actionsRunId)},'Source Commit':{rich_text:richText(payload.sourceGitCommit)},'Payload Hash':{rich_text:richText(payload.payloadHash)},'Screening Status':{rich_text:richText('complete')},'Notion Status':{rich_text:richText(status)},'Deploy Status':{rich_text:richText(state.deployStatus||'pending')},'Selected Count':{number:payload.selectedStocks.length},'Trust Count':{number:payload.strategies.trust.length},'Growth Count':{number:payload.strategies.growth.length},'Low Position Count':{number:payload.strategies.lowPosition.length},'Generated At':{date:{start:payload.generatedAt}},'Quality':{rich_text:richText(payload.freshness)},'Expected Count':{number:payload.selectedStocks.length},'Archived Count':{number:status==='complete'?payload.selectedStocks.length:0},'Actions URL':{url:state.actionsRunId?`https://github.com/pingpongtech-uskg/stock-web-pages/actions/runs/${state.actionsRunId}`:null},'Archive Method':{rich_text:richText(state.archiveMethod||'actions_artifact')},'Archive Source Commit':{rich_text:richText(state.archiveCommit||'')},'Archive URL':{url:state.databaseId?`https://www.notion.so/${state.databaseId.replaceAll('-','')}`:null},'Child Database ID':{rich_text:richText(state.databaseId||'')},'Child Data Source ID':{rich_text:richText(state.dataSourceId||'')},'Error Summary':{rich_text:richText(state.deployError||'')},'Coverage':{rich_text:richText(JSON.stringify(payload.coverage))},'Formula Versions':{rich_text:richText(JSON.stringify(payload.formulaVersions))},'Financial Cutoff':{rich_text:richText([...new Set(payload.selectedStocks.map(stock=>stock.provenance.financialCutoff).filter(Boolean))].join(', '))},...(status==='complete'?{'Active Revision':{rich_text:richText(payload.revision)}}:{})};
}
function summary(state) {
  const p=state.payload;
  return `Archive ${p.marketDate}; revision ${p.revision}; selected ${p.selectedStocks.length}; trust ${p.strategies.trust.length}; growth ${p.strategies.growth.length}; lowPosition ${p.strategies.lowPosition.length}; run ${p.runId}; Actions ${p.actionsRunId}; request ${p.requestId}; source ${p.sourceGitCommit}; payload ${p.payloadHash}; coverage ${JSON.stringify(p.coverage)}; formula ${JSON.stringify(p.formulaVersions)}; deploy ${state.deployStatus||'pending'}.`;
}
function start(input,now=Date.now()) {
  if(!/^\d{4}-\d{2}-\d{2}$/.test(input.marketDate)||new Date(`${input.marketDate}T00:00:00Z`).toISOString().slice(0,10)!==input.marketDate) throw Error('invalid_market_date');
  if(!/^[a-zA-Z0-9_.:-]{1,160}$/.test(input.requestId)||!['screen','resume','diagnose','revision','legacy_archive'].includes(input.mode)) throw Error('invalid_operator_input');
  if(input.mode==='legacy_archive'&&(input.runKind!=='manual'||!['2026-09-08','2026-09-11','2026-09-18','2026-09-23','2026-09-24','2026-10-01'].includes(input.marketDate)))throw Error('legacy_operator_scope');
  if(input.actionsRunId!==undefined&&!/^\d{1,24}$/.test(String(input.actionsRunId))) throw Error('invalid_actions_run_id');
  if(input.preflightRetryOwner!==undefined&&(input.runKind!=='manual'||input.mode!=='screen'||!/^\d{1,24}$/.test(input.preflightRetryOwner)))throw Error('invalid_preflight_retry_owner');
  if(input.siteUrl!=='https://stockscreener.andyshih.uk') throw Error('invalid_site_url');
  const overdueAt=Date.parse(input.marketDate+'T11:30:00Z');
  const operationDeadline=input.runKind==='scheduled'?overdueAt:now+90*60000;
  return request({...input,startedAt:now,operationDeadline,deadline:Math.min(now+59*60000,operationDeadline),targetAt:Date.parse(input.marketDate+'T10:45:00Z'),overdueAt,screeningStatus:'pending',notionStatus:'pending',deployStatus:'pending',released:false},'calendar','public','GET',CALENDAR);
}
function next(state,now) {
  if(state.stage.startsWith('cache'))return cacheOperation.nextCache(state,cacheApi(now));
  if(state.stage.startsWith('restore'))return restoreOperation.nextRestore(state,cacheApi(now));
  switch(state.stage) {
    case 'done':return done(state);
    case 'holiday':return checkpoint({...state,released:true,screeningStatus:'skipped_non_trading',notionStatus:'skipped',deployStatus:'skipped'},'done');
    case 'findRun':return findRuns(state);
    case 'failedRunJobs':return request(state,'failedRunJobs','github','GET',`${REPO}/actions/runs/${state.actionsRunId}/jobs?per_page=100`);
    case 'failedRunArtifacts':return request(state,'failedRunArtifacts','github','GET',`${REPO}/actions/runs/${state.actionsRunId}/artifacts?per_page=100`);
    case 'dispatch':return request({...state,dispatchIntent:true,dispatchStartedAt:state.dispatchStartedAt||now},'dispatch','github','POST',`${REPO}/actions/workflows/daily.yml/dispatches`,{ref:'main',inputs:{request_id:state.requestId,market_date:state.marketDate,source_mode:'publish',...(state.restoreStatus==='verified'?restoreOperation.restoreDispatchInputs(state):{})}});
    case 'pollRun':return request(state,'pollRun','github','GET',`${REPO}/actions/runs/${state.actionsRunId}`,null,15);
    case 'artifactList':return request(state,'artifactList','github','GET',`${REPO}/actions/runs/${state.actionsRunId}/artifacts?per_page=100`);
    case 'publicationExport':return request(state,'publicationExport','github','GET',`${REPO}/contents/public/data/screening-export.json?ref=${state.publication.publishedGitCommit}`);
    case 'legacyRef':return state.archiveCommit?archiveContents(state,'legacyIndex','/data/archive/v1/index.json'):request(state,'legacyRef','github','GET',`${REPO}/git/ref/heads/main`);
    case 'legacyExport':return archiveContents(state,'legacyExport',state.archivePath);
    case 'rootSchema':return request(state,'rootSchema','notion','GET',`https://api.notion.com/v1/data_sources/${ROOT_SOURCE}`);
    case 'findDaily':return findDaily(state);
    case 'writeFailure':return request(state,'writeFailure','notion','PATCH',`https://api.notion.com/v1/pages/${state.pageId}`,{properties:rootProperties(state,'failure_metadata')});
    case 'findDatabase':return findDatabase({...state,cursor:undefined,children:[]});
    case 'queryRows':return queryRows({...state,cursor:undefined,archiveRows:[]});
    case 'verifyRows':return queryRows({...state,cursor:undefined,archiveRows:[]},'verifyRows');
    case 'summaryRead':return request(state,'summaryRead','notion','GET',`https://api.notion.com/v1/blocks/${state.pageId}/children?page_size=100${state.cursor?'&start_cursor='+encodeURIComponent(state.cursor):''}`);
    case 'liveProbe':
    case 'liveVerify':return request(state,state.stage,'public','GET',liveUrl(state,now));
    default:throw Error('unknown_stage:'+state.stage);
  }
}
function cacheApi(now){return {request,checkpoint:(state,nextStage)=>checkpoint(state,nextStage,now),next:state=>next(state,now),fail};}
function advance(original,response,now=Date.now()) {
  const state={...original}; const status=Number(response?.statusCode??200); let body=response?.body??response?.data;
  if(typeof body==='string'&&!['liveProbe','liveVerify'].includes(state.stage)) {try{body=JSON.parse(body);}catch{/* Redirects may have no JSON body. */}}
  if(state.lockSha&&now>state.deadline) return fail(state,'writer_deadline');
  if(/^cache_[a-z_]+$/.test(response?.cacheError||''))return fail({...state,cacheStatus:'failed'},response.cacheError);
  if(['cacheDownload','restoreDownload'].includes(state.stage)&&(status===403||status===429||status>=500||response?.error)){
    if((state.retry||0)>=(status===429?8:3))return fail({...state,cacheStatus:'failed'},'cache_download_failed');
    const renewed=state.stage==='restoreDownload'?restoreOperation.nextRestore({...state,stage:'restoreFile',retry:(state.retry||0)+1},cacheApi(now)):cacheOperation.nextCache({...state,stage:'cacheGetFile',retry:(state.retry||0)+1},cacheApi(now));
    return {...renewed,delaySeconds:status===429?retrySeconds(response.headers?.['retry-after'],now):2**((state.retry||0)+1)};
  }
  if(status===429) {
    if((state.retry||0)>=8) return fail(state,'rate_limit_exhausted');
    return result({...state,retry:(state.retry||0)+1},state.op,retrySeconds(response.headers?.['retry-after'],now));
  }
  if(state.stage==='checkpoint') {
    if([409,422].includes(status)) return fail({...state,lockSha:undefined},'writer_conflict');
    if(status<200||status>=300) return done({...state,errorCategory:'checkpoint_failed',errorMessage:'State write ambiguous; resume reads GitHub state before any write.'});
    if(typeof body?.content?.sha!=='string'||!body.content.sha||body.content.sha.length>64||!/^[a-zA-Z0-9_-]+$/.test(body.content.sha)) return done({...state,errorCategory:'checkpoint_write_ambiguous',errorMessage:'State write response was incomplete; recovery must read GitHub state before writing again.'});
    const committed={...state,lockSha:body.content.sha,stage:state.nextStage,retry:0};
    try {return {...next(committed,now),ledgerRequired:true};}
    catch {
      const terminal={...committed,released:true,screeningStatus:committed.screeningStatus==='pending'?'failed':committed.screeningStatus||'failed',recordFailure:false,errorCategory:'checkpoint_advance_failed',errorMessage:'The state checkpoint was saved, but the next request could not be prepared. Resume from saved state.'};
      return checkpoint(terminal,'done',now);
    }
  }
  if(status>=500||response?.error) {
    if(['restoreBlobCreate','restoreTreeCreate','restoreCommitCreate','restoreRefCreate'].includes(state.stage))return restoreOperation.ambiguousRestore(state,cacheApi(now));
    if(['cacheCreateUpload','cacheSendUpload','cacheAppend'].includes(state.stage))return cacheOperation.ambiguousCacheWrite(state,cacheApi(now));
    const readStage={createDaily:'findDaily',createDatabase:'findDatabase',createStock:'queryRows',appendSummary:'summaryRead'}[state.stage];
    if(readStage) return next({...state,stage:readStage,retry:(state.retry||0)+1},now);
    if(state.stage==='dispatch') return findRuns({...state,dispatchIntent:true,runPage:1},15);
    if(['liveProbe','liveVerify'].includes(state.stage)) return deploymentResult(state,'failed',['live_binary_missing','live_file_too_large','live_binary_read_failed'].includes(response.liveReadError)?response.liveReadError:'live_http_'+status,now);
    if((state.retry||0)<3&&state.op?.method==='GET') return result({...state,retry:(state.retry||0)+1},state.op,2**((state.retry||0)+1));
    return fail(state,'external_http_'+status);
  }
  if(['liveProbe','liveVerify'].includes(state.stage)&&status>=400) return deploymentResult(state,'failed','live_http_'+status,now);
  if(state.stage==='createBranch'&&status===422) return request(state,'branch','github','GET',`${REPO}/git/ref/heads/n8n-state`);
  const allow404=['branch','state','restoreState','restoreIndex','restoreBlobGet','restoreTreeGet','restoreCommitGet','restoreRefGet'];
  if(state.stage==='restoreRefCreate'&&status===422)return restoreOperation.ambiguousRestore(state,cacheApi(now));
  if(state.stage==='dispatch'&&response.preflightFailed===true&&status===400&&body?.message==='Inputs: Invalid JSON') return fail({...state,dispatchIntent:false,screeningStatus:'failed'},'dispatch_preflight_failed',body.message);
  if(status>=400&&!allow404.includes(state.stage)) return fail(state,'external_http_'+status,body?.message);
  try {return advanceSuccess(state,body,status,response,now);} catch(error){return fail(state,error.message.split(':')[0],error.message);}
}
function advanceSuccess(state,body,status,response,now) {
  if(state.stage.startsWith('restore'))return restoreOperation.advanceRestore(state,{...response,body,statusCode:status},now,cacheApi(now));
  if(state.stage.startsWith('cache'))return cacheOperation.advanceCache(state,{...response,body,statusCode:status},now,cacheApi(now));
  switch(state.stage) {
    case 'calendar': {
      if(state.resolveLatest&&state.mode!=='diagnose') {
        const marketDate=latestCompletedSession(body,now);
        state={...state,requestedAtDate:state.marketDate,marketDate,requestId:state.automaticRequestId?'stockscreener:'+marketDate.replaceAll('-','')+':v1':state.requestId,targetAt:Date.parse(marketDate+'T10:45:00Z'),overdueAt:Date.parse(marketDate+'T11:30:00Z')};
      }
      const isOpen=calendarOpen(body,state.marketDate);
      if(isOpen&&state.mode!=='diagnose'&&state.mode!=='legacy_archive') {
        try {
          const previousSessionDate=latestCompletedSession(body,Date.parse(state.marketDate+'T00:00:00Z')-8*3600000);
          state={...state,previousSessionDate,previousSessionResolution:'official_calendar'};
        } catch(error) {
          if(error.message!=='calendar_year_boundary')throw error;
          state={...state,previousSessionDate:null,previousSessionResolution:'calendar_boundary'};
        }
      }
      if(state.mode==='diagnose') return request({...state,isOpen},'diagnoseDatabase','notion','GET',`https://api.notion.com/v1/databases/${ROOT_DATABASE}`);
      if(state.runKind==='scheduled'&&now>=state.operationDeadline) return done({...state,isOpen,errorCategory:'operation_overdue',errorMessage:'19:30 Asia/Taipei deadline passed; explicit manual resume is required.'});
      return request({...state,isOpen},'branch','github','GET',`${REPO}/git/ref/heads/n8n-state`);
    }
    case 'diagnoseDatabase':
      if(!body.data_sources?.some(source=>source.id===ROOT_SOURCE)) throw Error('notion_database_source_mismatch');
      return request(state,'diagnoseSource','notion','GET',`https://api.notion.com/v1/data_sources/${ROOT_SOURCE}`);
    case 'diagnoseSource':
      if(body.properties?.['名稱']?.type!=='title') throw Error('notion_title_property');
      return done({...state,screeningStatus:'diagnostic_verified',notionStatus:'credential_verified',deployStatus:'not_tested',notionDatabaseId:ROOT_DATABASE,notionDataSourceId:ROOT_SOURCE});
    case 'branch':
      if(status===404) return request(state,'mainRef','github','GET',`${REPO}/git/ref/heads/main`);
      return request(state,'state','github','GET',contents(state)+'?ref=n8n-state');
    case 'mainRef':return request(state,'createBranch','github','POST',`${REPO}/git/refs`,{ref:'refs/heads/n8n-state',sha:body.object.sha});
    case 'createBranch':return request(state,'state','github','GET',contents(state)+'?ref=n8n-state');
    case 'state': {
      const existing=status===404?null:JSON.parse(Buffer.from(body.content,'base64').toString('utf8'));
      if(existing?.owner!==state.owner&&!existing?.released&&existing?.owner&&now<Number(existing.deadline)+60000) return fail(state,'writer_busy');
      if(state.mode==='screen'&&state.automaticRequestId&&!state.preflightRetryOwner&&existing?.marketDate===state.marketDate&&existing.archiveMethod!=='legacy_archive'&&existing.requestId!==state.requestId){
        if(!/^[a-zA-Z0-9_.:-]{1,160}$/.test(existing.requestId||'')||(existing.actionsRunId&&!/^\d{1,24}$/.test(String(existing.actionsRunId))))throw Error('invalid_stored_request_lineage');
        state={...state,requestId:existing.requestId,automaticRequestAdoptedFrom:state.requestId};
      }
      const sameRequest=existing?.requestId===state.requestId||(state.mode==='legacy_archive'&&existing?.archiveMethod==='legacy_archive');
      const correctPreflight=!!state.preflightRetryOwner;
      if(correctPreflight&&(!sameRequest||existing?.marketDate!==state.marketDate||existing?.owner!==state.preflightRetryOwner||existing.released!==true||existing.actionsRunId||!existing.dispatchIntent||existing.errorCategory!=='dispatch_run_not_found'))return fail({...state,lockSha:undefined},'preflight_correction_scope');
      if(existing?.requestId&&!sameRequest&&state.mode!=='revision') throw Error('request_correction_requires_revision');
      if(existing?.released&&sameRequest&&existing.screeningStatus==='complete'&&existing.notionStatus==='complete'&&existing.deployStatus==='verified'&&(existing.archiveMethod==='legacy_archive'||existing.cacheStatus==='verified')) return done({...existing,owner:state.owner,screeningStatus:'already_complete'});
      const resume=sameRequest?existing:{};
      const manualOverride=state.runKind==='manual'&&['screen','resume','legacy_archive'].includes(state.mode)&&!!resume.requestId;
      const operationDeadline=manualOverride?state.operationDeadline:(resume.operationDeadline||state.operationDeadline);
      const audit=manualOverride?{scheduledCutoff:resume.scheduledCutoff||resume.overdueAt,manualDeadlineOverride:true,manualResumedAt:now}:{};
      const correction=correctPreflight?{dispatchIntent:false,preflightRetryOwner:undefined,confirmedPreflightCorrectionFrom:state.preflightRetryOwner,errorCategory:'',errorMessage:''}:{};
      const saved={...state,...resume,...audit,...correction,owner:state.owner,operationDeadline,deadline:Math.min(state.deadline,operationDeadline),released:false,lockSha:status===404?undefined:body.sha,mode:state.mode,runKind:state.runKind,siteUrl:state.siteUrl};
      const stage=!state.isOpen?'holiday':state.mode==='legacy_archive'?'legacyRef':saved.actionsRunId?'pollRun':'findRun';
      return checkpoint(saved,stage);
    }
    case 'findRun': {
      const runs=body.workflow_runs;if(!Array.isArray(runs)) throw Error('actions_schema');
      const matches=[...(state.runMatches||[]),...runs.filter(run=>run.display_title===`Daily screening | ${state.requestId} | ${state.marketDate}`)];
      const match=selectRun(matches,state);
      if(runs.length===100) {
        if((state.runPage||1)>=10) throw Error('actions_scan_limit');
        return findRuns({...state,runPage:(state.runPage||1)+1,runMatches:matches});
      }
      if(match) return checkpoint({...state,actionsRunId:String(match.id),runHeadSha:match.head_sha,runPage:1,runMatches:[]},'pollRun');
      if(state.dispatchIntent) {
        if(now-(state.dispatchStartedAt||state.startedAt)>5*60000) return fail(state,'dispatch_run_not_found','Dispatch was attempted; never resend without new operator request ID.');
        return findRuns({...state,runPage:1},15);
      }
      if(state.mode==='resume') return fail(state,'resume_run_not_found');
      return restoreOperation.beginRestore(state,cacheApi(now));
    }
    case 'dispatch':return findRuns({...state,dispatchIntent:true,runPage:1},15);
    case 'pollRun': {
      if(!selectRun([body],state)||String(body.id)!==state.actionsRunId) throw Error('actions_run_lineage');
      if(body.status!=='completed') return next({...state,stage:'pollRun'},now);
      if(body.conclusion!=='success') {
        if(retryableFailedRun(state,body)) return checkpoint({...state,failedRunAttempt:body.run_attempt,failedRunTitle:body.display_title,failedRunHeadSha:body.head_sha},'failedRunJobs');
        return failedRun(state,body.conclusion);
      }
      return checkpoint({...state,screeningStatus:'complete',runHeadSha:body.head_sha},'artifactList');
    }
    case 'failedRunJobs': {
      const failedStep=retryableSourceFailure(body,state);
      if(!failedStep) return failedRun(state,'failure');
      return checkpoint({...state,automaticRetryCandidateStep:failedStep},'failedRunArtifacts');
    }
    case 'failedRunArtifacts': {
      if(!retryArtifactsAbsent(body,state)) return failedRun(state,'failure');
      if(state.requestId.length>153) return failedRun(state,'failure');
      const originalRequestId=state.requestId;
      const retryRequestId=`${originalRequestId}:retry1`;
      return checkpoint({...state,requestId:retryRequestId,originalRequestId,automaticRetryCount:1,
        automaticRetry:{count:1,originalRequestId,originalActionsRunId:String(state.actionsRunId),failedStep:state.automaticRetryCandidateStep,failedHeadSha:state.failedRunHeadSha,failedAttempt:state.failedRunAttempt},
        actionsRunId:undefined,runHeadSha:undefined,dispatchIntent:false,dispatchStartedAt:undefined,runPage:1,runMatches:[],screeningStatus:'pending',recordFailure:false,errorCategory:'',errorMessage:''},'findRun');
    }
    case 'artifactList': {
      const artifacts=body.artifacts?.filter(artifact=>artifact.name==='screening-export'&&!artifact.expired);
      if(artifacts?.length!==1) throw Error('artifact_missing_or_ambiguous');
      const artifact=artifacts[0];
      if(artifact.workflow_run&&(String(artifact.workflow_run.id)!==state.actionsRunId||artifact.workflow_run.head_sha!==state.runHeadSha)) throw Error('artifact_lineage');
      return request({...state,artifactId:String(artifact.id)},'artifactRedirect','github','GET',`${REPO}/actions/artifacts/${artifact.id}/zip`);
    }
    case 'artifactRedirect': {
      const location=response.headers?.location;
      if(status!==302||typeof location!=='string'||!/^https:\/\/[a-zA-Z0-9.-]+\.(blob\.core\.windows\.net|actions\.githubusercontent\.com|githubusercontent\.com)\//.test(location)) throw Error('artifact_redirect');
      return request(state,'artifactZip','zip','GET',location);
    }
    case 'artifactZip': {
      const payload=validateExport(body.rawExport,{marketDate:state.marketDate,requestId:state.requestId,actionsRunId:state.actionsRunId});
      const publication=body.publication;
      if(payload.sourceGitCommit!==state.runHeadSha) throw Error('source_commit_lineage');
      for(const field of ['requestId','marketDate','runId','payloadHash','sourceGitCommit','actionsRunId']) if(publication[field]!==payload[field]) throw Error('publication_lineage:'+field);
      if(!/^[a-f0-9]{40}$/.test(publication.publishedGitCommit)) throw Error('publication_commit');
      return checkpoint({...state,payload,publication,payloadHash:payload.payloadHash,runId:payload.runId,revision:payload.revision,expectedCount:payload.selectedStocks.length},'publicationExport');
    }
    case 'publicationExport': {
      const payload=validateExport(contentBytes(body),{marketDate:state.marketDate,requestId:state.requestId,actionsRunId:state.actionsRunId});
      if(payload.payloadHash!==state.payloadHash||payload.sourceGitCommit!==state.runHeadSha||payload.runId!==state.runId)throw Error('published_export_lineage');
      return request(state,'publicationMain','github','GET',`${REPO}/compare/${state.publication.publishedGitCommit}...main`);
    }
    case 'publicationMain': {
      if(!['ahead','identical'].includes(body.status)||body.base_commit?.sha!==state.publication.publishedGitCommit)throw Error('publication_not_on_main');
      return checkpoint({...state,publicationStatus:'verified'},'liveProbe');
    }
    case 'legacyRef': {
      if(!/^[a-f0-9]{40}$/.test(body.object?.sha))throw Error('archive_source_commit');
      return archiveContents({...state,archiveCommit:body.object.sha,archiveMethod:'legacy_archive'},'legacyIndex','/data/archive/v1/index.json');
    }
    case 'legacyIndex': {
      const index=JSON.parse(contentBytes(body));
      if(index.schemaVersion!=='screening-history-index-v1'||!Array.isArray(index.months))throw Error('archive_index_schema');
      const matches=index.months.filter(month=>month.month===state.marketDate.slice(0,7)&&month.marketDates?.includes(state.marketDate));
      if(matches.length!==1||!/^\/data\/archive\/v1\/months\/\d{4}-\d{2}\.[a-f0-9]{12}\.json$/.test(matches[0].path)||!/^[a-f0-9]{64}$/.test(matches[0].sha256))throw Error('archive_month_ref');
      return archiveContents({...state,archiveMonth:matches[0]},'legacyMonth',matches[0].path);
    }
    case 'legacyMonth': {
      const raw=contentBytes(body);if(sha256(raw)!==state.archiveMonth.sha256||Buffer.byteLength(raw)!==state.archiveMonth.bytes)throw Error('archive_month_hash');
      const month=JSON.parse(raw);if(month.schemaVersion!=='screening-history-month-v1'||month.month!==state.marketDate.slice(0,7)||!Array.isArray(month.records))throw Error('archive_month_schema');
      const records=month.records.filter(record=>record.marketDate===state.marketDate);if(records.length!==1||records[0].legacy!==true)throw Error('archive_legacy_record');
      const record=records[0];const refs=record.revisionRefs?.filter(ref=>ref.revision===record.revision&&ref.legacy===true);
      if(!/^[a-f0-9]{12}$/.test(record.revision)||refs?.length!==1||refs[0].path!==`/data/archive/v1/revisions/${state.marketDate}.${record.revision}.json`||!/^[a-f0-9]{64}$/.test(refs[0].sha256)||refs[0].runId!==record.runId)throw Error('archive_revision_ref');
      return checkpoint({...state,requestId:`legacy:${state.marketDate}:${record.revision}`,archivePath:refs[0].path,archiveExpected:{marketDate:state.marketDate,revision:record.revision,runId:record.runId,sha256:refs[0].sha256,archiveCommit:state.archiveCommit},archiveMethod:'legacy_archive'},'legacyExport');
    }
    case 'legacyExport': {
      const payload=validateLegacyArchive(contentBytes(body),state.archiveExpected);
      return checkpoint({...state,payload,payloadHash:payload.payloadHash,runId:payload.runId,revision:payload.revision,expectedCount:payload.selectedStocks.length,screeningStatus:'complete',publicationStatus:'legacy_commit_verified'},'liveProbe');
    }
    case 'rootSchema': {
      if(body.properties?.['名稱']?.type!=='title') throw Error('notion_root_title');
      const missing=Object.fromEntries(Object.entries(ALL_ROOT_FIELDS).filter(([name])=>!body.properties[name]));
      for(const [name,definition] of Object.entries(ALL_ROOT_FIELDS)) if(body.properties[name]&&body.properties[name].type!==Object.keys(definition)[0]) throw Error('notion_root_schema:'+name);
      if(Object.keys(missing).length) return request(state,'rootSchemaUpdate','notion','PATCH',`https://api.notion.com/v1/data_sources/${ROOT_SOURCE}`,{properties:missing});
      return findDaily(state);
    }
    case 'rootSchemaUpdate':return findDaily(state);
    case 'findDaily': {
      if(body.has_more||body.results?.length>1) throw Error('duplicate_daily_page');
      const page=body.results?.[0];
      if(page) return checkpoint({...state,pageId:page.id,notionPageId:page.id,cacheActiveManifestHash:readProperty(page.properties?.['Cache Active Revision'])||state.cacheActiveManifestHash},state.recordFailure?'writeFailure':'findDatabase');
      return request(state,'createDaily','notion','POST','https://api.notion.com/v1/pages',{parent:{type:'data_source_id',data_source_id:ROOT_SOURCE},properties:{'名稱':{title:richText(state.marketDate.replaceAll('-',''))},...rootProperties(state,'pending')}});
    }
    case 'createDaily':return checkpoint({...state,pageId:body.id,notionPageId:body.id},state.recordFailure?'writeFailure':'findDatabase');
    case 'writeFailure':return checkpoint({...state,notionStatus:'failure_metadata',released:true},'done');
    case 'findDatabase': {
      const children=[...(state.children||[]),...(body.results||[])];
      if(body.has_more) return findDatabase({...state,children,cursor:body.next_cursor});
      const databases=children.filter(block=>block.type==='child_database'&&block.child_database.title===state.marketDate.replaceAll('-',''));
      if(databases.length>1) throw Error('duplicate_daily_database');
      if(databases.length) return request({...state,databaseId:databases[0].id},'databaseMetadata','notion','GET',`https://api.notion.com/v1/databases/${databases[0].id}`);
      return request(state,'createDatabase','notion','POST','https://api.notion.com/v1/databases',{parent:{type:'page_id',page_id:state.pageId},title:richText(state.marketDate.replaceAll('-','')),is_inline:true,initial_data_source:{properties:stockSchema()}});
    }
    case 'createDatabase':
    case 'databaseMetadata': {
      if(body.data_sources?.length!==1||!body.data_sources[0].id) throw Error('notion_child_source');
      return checkpoint({...state,databaseId:body.id,dataSourceId:body.data_sources[0].id,notionDatabaseId:body.id,notionDataSourceId:body.data_sources[0].id},'queryRows');
    }
    case 'queryRows':
    case 'verifyRows':return handleRows(state,body);
    case 'createStock': {
      const remaining=(state.pendingStocks||[]).slice(1);
      if(remaining.length) return createStock({...state,pendingStocks:remaining});
      return next({...state,stage:'verifyRows'},now);
    }
    case 'archiveDuplicate':return next({...state,stage:'queryRows'},now);
    case 'summaryRead': {
      const marker=`Payload ${state.payload.payloadHash}`;
      const found=(body.results||[]).some(block=>block.type==='paragraph'&&block.paragraph.rich_text?.map(part=>part.plain_text||part.text?.content||'').join('').includes(marker));
      if(found) return next({...state,stage:'liveVerify'},now);
      if(body.has_more) return next({...state,stage:'summaryRead',cursor:body.next_cursor},now);
      return request(state,'appendSummary','notion','PATCH',`https://api.notion.com/v1/blocks/${state.pageId}/children`,{children:[{object:'block',type:'paragraph',paragraph:{rich_text:richText(`Payload ${state.payload.payloadHash}\n${summary(state)}`)}}]});
    }
    case 'appendSummary':return next({...state,stage:'liveVerify'},now);
    case 'liveProbe':
    case 'liveVerify': {
      let deployStatus='failed',deployError='live_payload_mismatch';
      try {
        const live=state.archiveMethod==='legacy_archive'?validateLegacyArchive(body,state.archiveExpected):validateExport(body,{marketDate:state.marketDate,requestId:state.requestId,actionsRunId:state.actionsRunId});
        if(live.payloadHash===state.payload.payloadHash&&live.runId===state.payload.runId&&live.sourceGitCommit===state.payload.sourceGitCommit) {deployStatus='verified';deployError=undefined;}
      }catch(error){deployError=error.message;}
      return deploymentResult(state,deployStatus,deployError,now);
    }
    case 'finishNotion':return checkpoint({...state,notionStatus:'complete',released:true,errorCategory:state.deployStatus==='verified'?undefined:'deploy_pending',errorMessage:state.deployError},'done');
    default:throw Error('unknown_stage:'+state.stage);
  }
}
function readProperty(value) {return value?.rich_text?.map(part=>part.plain_text||part.text?.content||'').join('')||'';}
function handleRows(state,body) {
  const rows=[...(state.archiveRows||[]),...(body.results||[])];
  if(body.has_more) return queryRows({...state,archiveRows:rows,cursor:body.next_cursor},state.stage);
  const keys=rows.map(row=>readProperty(row.properties['Row Key']));
  const selected=state.payload.selectedStocks;
  const expectedKeys=selected.map(stock=>`${state.payload.payloadHash}:${stock.code}`);
  if(keys.some(key=>!expectedKeys.includes(key))) throw Error('extra_stock_rows');
  for(const row of rows) {
    const stock=selected.find(item=>`${state.payload.payloadHash}:${item.code}`===readProperty(row.properties['Row Key']));
    const expected=stockProperties(stock,state.payload);
    for(const [name,property] of Object.entries(expected)) {
      const actual=row.properties[name]; const type=Object.keys(property)[0];
      if(type==='title'&&actual?.title?.map(part=>part.plain_text||part.text?.content||'').join('')!==property.title.map(part=>part.text.content).join(''))throw Error('archive_title_mismatch');
      if(type==='number'&&actual?.number!==property.number) throw Error('archive_metric_mismatch:'+name);
      if(type==='rich_text'&&readProperty(actual)!==readProperty(property)) throw Error('archive_text_mismatch:'+name);
      if(type==='multi_select'&&actual?.multi_select?.map(item=>item.name).sort().join(',')!==property.multi_select.map(item=>item.name).sort().join(',')) throw Error('archive_strategy_mismatch');
    }
  }
  if(new Set(keys).size!==keys.length) {
    const ordered=[...rows].sort((a,b)=>String(a.created_time).localeCompare(String(b.created_time))||a.id.localeCompare(b.id));
    const duplicate=ordered.find((row,index)=>ordered.slice(0,index).some(prior=>readProperty(prior.properties['Row Key'])===readProperty(row.properties['Row Key'])));
    return request(state,'archiveDuplicate','notion','PATCH',`https://api.notion.com/v1/pages/${duplicate.id}`,{archived:true});
  }
  const pendingStocks=selected.filter(stock=>!keys.includes(`${state.payload.payloadHash}:${stock.code}`));
  if(state.stage==='verifyRows'&&pendingStocks.length) throw Error('archive_incomplete');
  if(pendingStocks.length) return createStock({...state,pendingStocks,archiveRows:[],cursor:undefined});
  return checkpoint({...state,archiveRows:[],cursor:undefined,archivedCount:rows.length,notionStatus:'rows_verified'},state.archiveMethod==='legacy_archive'?'summaryRead':'cacheRun');
}
function createStock(state) {return request(state,'createStock','notion','POST','https://api.notion.com/v1/pages',{parent:{type:'data_source_id',data_source_id:state.dataSourceId},properties:stockProperties(state.pendingStocks[0],state.payload)});}
function finishNotion(state) {
  if(state.archiveMethod!=='legacy_archive'&&state.cacheStatus!=='verified')return fail(state,'cache_required_before_archive_completion');
  return request(state,'finishNotion','notion','PATCH',`https://api.notion.com/v1/pages/${state.pageId}`,{properties:{...rootProperties(state,'complete'),'Summary':{rich_text:richText(summary(state))}}});
}
function deploymentResult(state,deployStatus,deployError,now) {
  const updated={...state,deployStatus,deployError};
  if(state.stage==='liveProbe') return checkpoint(updated,'rootSchema');
  if(deployStatus!=='verified'&&(state.deployAttempts||0)<20&&now+15000<state.deadline) return request({...updated,deployAttempts:(state.deployAttempts||0)+1},'liveVerify','public','GET',liveUrl(state,now),null,15);
  return finishNotion(updated);
}
function liveUrl(state,now){return `${state.siteUrl}${state.archiveMethod==='legacy_archive'?state.archivePath:'/data/screening-export.json'}?run=${encodeURIComponent(state.actionsRunId||state.revision||'')}&t=${now}`;}
if(typeof module!=='undefined') module.exports={start,advance,calendarOpen,latestCompletedSession,selectRun,durable};
