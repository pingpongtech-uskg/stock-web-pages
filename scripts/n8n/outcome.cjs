// Sanitized observations survive execution retention; recovery authority remains GitHub CAS.
function safeOutcomeText(value) {return String(value||'').replace(/https?:\/\/\S+/g,'[URL redacted]').slice(0,1000);}
function operationOutcome(state) {
  const screeningStatus=state.screeningStatus||'pending',notionStatus=state.notionStatus||'pending',deployStatus=state.deployStatus||'pending';
  const outcome=state.cacheStatus==='pending_recovery'&&state.released===true?'pending_recovery':screeningStatus==='diagnostic_verified'?'diagnostics_only':screeningStatus==='skipped_non_trading'?'skipped_non_trading':screeningStatus==='already_complete'?'already_complete':screeningStatus==='complete'&&notionStatus==='complete'?(deployStatus==='verified'?'complete':'deployment_pending'):state.errorCategory?'failed':'in_progress';
  const actionsRunId=/^\d{1,24}$/.test(state.actionsRunId||'')?state.actionsRunId:'';
  const pageId=/^[a-f0-9-]{36}$/.test(state.notionPageId||'')?state.notionPageId:'';
  return {outcome,marketDate:state.marketDate,requestedAtDate:state.requestedAtDate||state.marketDate,requestId:state.requestId,stage:state.stage,owner:state.owner,screeningStatus,notionStatus,deployStatus,publicationStatus:state.publicationStatus||'pending',cacheStatus:state.archiveMethod==='legacy_archive'?'legacy_not_applicable':state.cacheStatus||'pending',cacheManifestHash:/^[a-f0-9]{64}$/.test(state.cacheManifestHash||'')?state.cacheManifestHash:null,cachePreviousTradingDate:state.cachePreviousTradingDate||null,cacheMetricsComplete:typeof state.cacheMetricsComplete==='boolean'?state.cacheMetricsComplete:null,cachePartsExpected:state.cachePartsExpected??null,cachePartsVerified:state.cachePartsVerified??null,cacheIndependentRawSemanticsVerified:state.cacheIndependentRawSemanticsVerified===true,cacheRawSemanticsVerifiedByProducer:state.cacheRawSemanticsVerifiedByProducer===true,actionsRunId,runId:state.runId||'',revision:state.revision||'',payloadHash:state.payloadHash||'',expectedCount:state.expectedCount??null,archivedCount:state.archivedCount??null,actionsUrl:actionsRunId?'https://github.com/pingpongtech-uskg/stock-web-pages/actions/runs/'+actionsRunId:null,notionUrl:pageId?'https://www.notion.so/'+pageId.replaceAll('-',''):null,publishedGitCommit:/^[a-f0-9]{40}$/.test(state.publication?.publishedGitCommit||'')?state.publication.publishedGitCommit:null,errorCategory:state.errorCategory||'',errorMessage:safeOutcomeText(state.errorMessage),diagnosticsOnly:screeningStatus==='diagnostic_verified',deadline:state.deadline||null,scheduledCutoff:state.scheduledCutoff||state.overdueAt||null,manualDeadlineOverride:state.manualDeadlineOverride||false};
}
function nativeDispatchResponse(value) {
  const error=value?.error;
  const code=Number(value?.statusCode||error?.statusCode||error?.httpCode||error?.cause?.statusCode||0);
  // Github v1.1 throws this exact local validation error before githubApiRequest.
  if(error&&code===0&&(error.message||error)==='Inputs: Invalid JSON')return {statusCode:400,body:{message:'Inputs: Invalid JSON'},headers:{},preflightFailed:true};
  const statusCode=code>=100&&code<600?code:error?503:204;
  return {statusCode,body:error?{message:safeOutcomeText(error.message||error)}:{},headers:value?.headers||error?.headers||error?.response?.headers||{},...(error&&statusCode>=500?{error:true}:{})};
}
if(typeof module!=='undefined')module.exports={operationOutcome,nativeDispatchResponse};
