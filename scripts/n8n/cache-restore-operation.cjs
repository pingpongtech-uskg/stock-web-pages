'use strict';
// Pure restoration bridge. Custody comes from the credentialed prior-day CAS,
// then fresh Notion metadata and exact attachment bytes. The runner uses trusted
// main code; this empty-base commit carries public data only, never executable code.
const {createHash}=require('crypto');
const marketCache=require('./market-cache.cjs');
const RESTORE_REPO='https://api.github.com/repos/pingpongtech-uskg/stock-web-pages';
const RESTORE_NOTION='https://api.notion.com/v1';
const restoreHash=bytes=>createHash('sha256').update(bytes).digest('hex');
const restoreCheck=(ok,why)=>{if(!ok)throw Error('restore_'+why);};
const restoreSha=value=>/^[a-f0-9]{40}$/.test(value||'');
const restoreUuid=value=>/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value||'');
const restoreCaption=block=>block.file?.caption?.map(p=>p.plain_text||p.text?.content||'').join('');
const restoreProp=(p,key)=>p?.[key]?.rich_text?.map(v=>v.plain_text||v.text?.content||'').join('');
const restoreSource=p=>({requestId:p.requestId,actionsRunId:p.actionsRunId,sourceGitCommit:p.runHeadSha});
const restoreName=name=>/^(?:manifest\.json|proof\.json|expected\.json|\d{4}-\d{2}-\d{2}\.[A-Za-z0-9_-]+\.\d+\.[a-f0-9]{64}\.json\.gz)$/.test(name);
function restoreDurable(state){const {restoreTransient,restorePrior,restoreDescriptor,restoreSignedUrl,restoreChildren,restoreFileMeta,restoreTreeEntries,restoreCommitBody,restoreGitFiles,op,...safe}=state;return safe;}
function beginRestore(state,api){
  if(!state.previousSessionDate&&state.previousSessionResolution==='calendar_boundary'){
    if(state.restoreCacheCandidateDate&&restoreSha(state.restoreInventoryRef))return restoreCandidate(state,api);
    return api.request({...state,restoreStatus:'checking'},'restoreIndexRef','github','GET',`${RESTORE_REPO}/git/ref/heads/n8n-state`);
  }
  if(!state.previousSessionDate)return api.checkpoint({...state,dispatchIntent:true,restoreStatus:'missing'},'dispatch');
  restoreCheck(/^\d{4}-\d{2}-\d{2}$/.test(state.previousSessionDate)&&state.previousSessionDate<state.marketDate,'date');
  return restoreCandidate({...state,restoreStatus:'checking',restoreCacheCandidateDate:state.previousSessionDate},api);
}
function restoreCandidate(state,api){
  const date=state.restoreCacheCandidateDate;restoreCheck(/^\d{4}-\d{2}-\d{2}$/.test(date||'')&&date<state.marketDate,'candidate_date');
  return api.request(state,'restoreState','github','GET',`${RESTORE_REPO}/contents/operations/days/${date}.json?ref=${state.restoreInventoryRef||'n8n-state'}`);
}
function restoreMissingCandidate(state,api){
  if(state.restoreCandidates&&state.restoreCandidateCursor+1<state.restoreCandidates.length){const cursor=state.restoreCandidateCursor+1;return restoreCandidate({...state,restoreCandidateCursor:cursor,restoreCacheCandidateDate:state.restoreCandidates[cursor]},api);}
  return api.checkpoint({...state,restoreStatus:'missing',dispatchIntent:true},'dispatch');
}
function validatePrior(p,state){
  restoreCheck(p.marketDate===(state.restoreCacheCandidateDate||state.previousSessionDate)&&p.cacheStatus==='verified'&&p.cacheManifestHash===p.cacheActiveManifestHash&&/^[a-f0-9]{64}$/.test(p.cacheManifestHash||'')&&/^[a-f0-9]{64}$/.test(p.cacheProofHash||''),'prior_custody');
  restoreCheck(restoreUuid(p.pageId)&&/^\d{1,24}$/.test(p.actionsRunId||'')&&restoreSha(p.runHeadSha)&&/^[A-Za-z0-9_.:-]{1,160}$/.test(p.requestId||'')&&/^\d{1,20}$/.test(p.cacheArtifactId||'')&&/^\d{1,20}$/.test(p.cacheRunWorkflowId||'')&&/^[a-f0-9]{64}$/.test(p.cacheArtifactSha256||'')&&/^[a-f0-9]{64}$/.test(p.cacheLatestHash||''),'prior_lineage');
  restoreCheck(Array.isArray(p.cacheFileMeta)&&p.cacheFileMeta.length>=3&&p.cacheFileMeta.length<=259&&new Set(p.cacheFileMeta.map(e=>e.name)).size===p.cacheFileMeta.length,'file_metadata');
  let total=0;for(const e of p.cacheFileMeta){restoreCheck(restoreName(e.name)&&/^[a-f0-9]{64}$/.test(e.sha256||'')&&Number.isSafeInteger(e.bytes)&&e.bytes>0&&e.bytes<=(e.name.endsWith('.gz')?4194304:1048576),'file_metadata');total+=e.bytes;}
  restoreCheck(total<=67*1024*1024&&['manifest.json','proof.json','expected.json'].every(name=>p.cacheFileMeta.some(e=>e.name===name)),'file_metadata');
}
const custodyKeys=['marketDate','requestId','actionsRunId','runHeadSha','pageId','screeningStatus','publicationStatus','cacheStatus','cacheManifestHash','cacheActiveManifestHash','cacheProofHash','cacheArtifactId','cacheRunWorkflowId','cacheArtifactSha256','cacheLatestHash','cacheFileMeta','cachePartsExpected','cachePartsVerified','cacheMetricsComplete','cacheRawSemanticsVerifiedByProducer','cacheIndependentRawSemanticsVerified','cachePreviousTradingDate'];
// Only a completed producer/readback can establish custody. A later operation's
// request/run is deliberately outside this descriptor, even on the same date.
function captureVerifiedCache(p,date){
  validatePrior(p,{previousSessionDate:date});
  restoreCheck(p.screeningStatus==='complete'&&p.publicationStatus==='verified'&&p.cachePartsExpected===p.cacheFileMeta.length&&p.cachePartsVerified===p.cachePartsExpected&&p.cacheRawSemanticsVerifiedByProducer===true&&typeof p.cacheIndependentRawSemanticsVerified==='boolean'&&typeof p.cacheMetricsComplete==='boolean','complete_custody');
  restoreCheck(/^\d{4}-\d{2}-\d{2}$/.test(p.cachePreviousTradingDate||'')&&p.cachePreviousTradingDate<date&&new Date(p.cachePreviousTradingDate+'T00:00:00Z').toISOString().slice(0,10)===p.cachePreviousTradingDate,'complete_custody');
  return {schemaVersion:'market-cache-custody-v1',...Object.fromEntries(custodyKeys.map(key=>[key,key==='cacheFileMeta'?p[key].map(({name,sha256,bytes})=>({name,sha256,bytes})):p[key]]))};
}
function cacheCustodyForDay(day,date){
  if(!Object.prototype.hasOwnProperty.call(day,'lastVerifiedCache'))return undefined;
  const p=day.lastVerifiedCache;
  restoreCheck(day.marketDate===date&&p?.schemaVersion==='market-cache-custody-v1'&&Object.keys(p).length===custodyKeys.length+1&&Object.keys(p).every(k=>k==='schemaVersion'||custodyKeys.includes(k)),'custody_descriptor');
  const verified=captureVerifiedCache(p,date);
  restoreCheck(day.cacheActiveManifestHash===p.cacheManifestHash,'custody_anchor');
  if(day.cacheStatus==='verified')restoreCheck(JSON.stringify(captureVerifiedCache(day,date))===JSON.stringify(verified),'custody_lineage');
  return verified;
}
function restoreGetPart(state,api){
  const e=state.restoreFileMeta[state.restoreCursor||0],id=state.restoreBlockIds?.[e.name];restoreCheck(restoreUuid(id),'block_id');
  return api.request(state,'restoreFile','notion','GET',`${RESTORE_NOTION}/blocks/${id}`);
}
function restoreChildren(state,api){return api.request(state,'restoreChildren','notion','GET',`${RESTORE_NOTION}/blocks/${state.restorePageId}/children?page_size=100${state.restoreChildrenCursor?'&start_cursor='+encodeURIComponent(state.restoreChildrenCursor):''}`);}
function gitObject(type,bytes){return createHash('sha1').update(Buffer.concat([Buffer.from(`${type} ${bytes.length}\0`),bytes])).digest('hex');}
function prepareRestoreDescriptor(state,now){
  const p=state.restorePrior;validatePrior(p,state);restoreCheck(state.marketDate>=p.marketDate,'target_date');
  const files=Object.fromEntries(Object.entries(state.restoreTransient?.files||{}).map(([name,data])=>[name,Buffer.from(data,'base64')]));
  restoreCheck(JSON.stringify(Object.keys(files).sort())===JSON.stringify(p.cacheFileMeta.map(e=>e.name).sort()),'file_set');
  for(const e of p.cacheFileMeta)restoreCheck(files[e.name].length===e.bytes&&restoreHash(files[e.name])===e.sha256,'file_hash');
  const manifest=JSON.parse(files['manifest.json']),expected=JSON.parse(files['expected.json']);
  restoreCheck(manifest.manifestHash===p.cacheManifestHash&&manifest.marketDate===p.marketDate&&expected.marketDate===p.marketDate&&restoreHash(files['proof.json'])===p.cacheProofHash,'manifest_custody');
  const group=expected.groups?.find(g=>g.kind==='published_stock_inputs');restoreCheck(group?.sourceSha256===p.cacheLatestHash,'published_custody');
  const shardNames=manifest.groups.flatMap(g=>g.shards.map(e=>e.name));
  marketCache.verifyCompressedMarketCache(manifest,Object.fromEntries(shardNames.map(name=>[name,files[name]])),{...expected,source:restoreSource(p),manifestHash:p.cacheManifestHash,producerProofSha256:p.cacheProofHash,artifactLineage:{repository:'pingpongtech-uskg/stock-web-pages',workflowId:p.cacheRunWorkflowId,artifactId:p.cacheArtifactId,artifactSha256:p.cacheArtifactSha256,...restoreSource(p)}},files['proof.json']);
  const descriptor={schemaVersion:'market-cache-restore-v1',repository:'pingpongtech-uskg/stock-web-pages',marketDate:p.marketDate,source:restoreSource(p),manifestHash:p.cacheManifestHash,files:[...p.cacheFileMeta].sort((a,b)=>a.name<b.name?-1:a.name>b.name?1:0).map(({name,sha256,bytes})=>({name,sha256,bytes}))};
  const raw=Buffer.from(JSON.stringify(descriptor));
  return {...state,restoreDescriptor:descriptor,restoreDescriptorSha256:restoreHash(raw),restoreManifestHash:p.cacheManifestHash,restoreOriginalSource:restoreSource(p),restoreCacheMarketDate:p.marketDate,restoreCreatedAt:new Date(Math.floor(Date.parse(manifest.generatedAt)/1000)*1000).toISOString().replace('.000Z','Z'),restoreGitFiles:[...Object.keys(files),'restore.json'].sort(),restoreBlobCursor:0,restoreTransient:{files:{...state.restoreTransient.files,'restore.json':raw.toString('base64')}}};
}
function prepareTree(state){
  const entries=state.restoreGitFiles.map(name=>({path:name,mode:'100644',type:'blob',sha:gitObject('blob',Buffer.from(state.restoreTransient.files[name],'base64'))}));
  const bytes=Buffer.concat(entries.map(e=>Buffer.concat([Buffer.from(`100644 ${e.path}\0`),Buffer.from(e.sha,'hex')])));
  const tree=gitObject('tree',bytes),person={name:'github-actions[bot]',email:'41898282+github-actions[bot]@users.noreply.github.com',date:state.restoreCreatedAt};
  const message=`[CF-Pages-Skip] chore: cache restore ${state.restoreManifestHash}\n`;
  const seconds=Date.parse(person.date)/1000;restoreCheck(Number.isSafeInteger(seconds),'commit_date');
  const identity=`${person.name} <${person.email}> ${seconds} +0000`;
  const raw=Buffer.from(`tree ${tree}\nauthor ${identity}\ncommitter ${identity}\n\n${message}`);
  return {...state,restoreTreeEntries:entries,restoreTreeSha:tree,restoreCommitSha:gitObject('commit',raw),restoreCommitBody:{message,tree,parents:[],author:person,committer:person}};
}
function restoreDispatchInputs(state){
  if(state.restoreStatus==='missing')return {};
  restoreCheck(state.restoreStatus==='verified'&&restoreSha(state.restoreCommitSha)&&/^[a-f0-9]{64}$/.test(state.restoreDescriptorSha256||'')&&state.restoreCacheMarketDate<=state.marketDate,'dispatch_context');
  const source=state.restoreOriginalSource;
  return {restore_commit:state.restoreCommitSha,restore_descriptor_sha256:state.restoreDescriptorSha256,restore_cache_market_date:state.restoreCacheMarketDate,restore_source_git_commit:source.sourceGitCommit,restore_actions_run_id:source.actionsRunId,restore_request_id:source.requestId};
}
function nextRestore(state,api){
  switch(state.stage){
    case 'restoreState':return beginRestore(state,api);
    case 'restoreIndexRef':return beginRestore({...state,restoreCacheCandidateDate:undefined},api);
    case 'restoreFile':return restoreGetPart(state,api);
    case 'restoreBlobGet':{
      if(state.restoreBlobCursor>=state.restoreGitFiles.length)return nextRestore({...prepareTree(state),stage:'restoreTreeGet'},api);
      const name=state.restoreGitFiles[state.restoreBlobCursor],sha=gitObject('blob',Buffer.from(state.restoreTransient.files[name],'base64'));
      return api.request({...state,restoreObjectSha:sha},'restoreBlobGet','github','GET',`${RESTORE_REPO}/git/blobs/${sha}`);
    }
    case 'restoreBlobCreate':return api.request(state,'restoreBlobCreate','github','POST',`${RESTORE_REPO}/git/blobs`,{encoding:'base64',content:state.restoreTransient.files[state.restoreGitFiles[state.restoreBlobCursor]]});
    case 'restoreTreeGet':return api.request(state,'restoreTreeGet','github','GET',`${RESTORE_REPO}/git/trees/${state.restoreTreeSha}`);
    case 'restoreTreeCreate':return api.request(state,'restoreTreeCreate','github','POST',`${RESTORE_REPO}/git/trees`,{tree:state.restoreTreeEntries});
    case 'restoreCommitGet':return api.request(state,'restoreCommitGet','github','GET',`${RESTORE_REPO}/git/commits/${state.restoreCommitSha}`);
    case 'restoreCommitCreate':return api.request(state,'restoreCommitCreate','github','POST',`${RESTORE_REPO}/git/commits`,state.restoreCommitBody);
    case 'restoreRefGet':return api.request(state,'restoreRefGet','github','GET',`${RESTORE_REPO}/git/ref/heads/n8n-cache-restore/${state.restoreManifestHash}`);
    case 'restoreRefCreate':return api.request(state,'restoreRefCreate','github','POST',`${RESTORE_REPO}/git/refs`,{ref:'refs/heads/n8n-cache-restore/'+state.restoreManifestHash,sha:state.restoreCommitSha});
    default:throw Error('restore_unknown_stage');
  }
}
function ambiguousRestore(state,api){
  const stage={restoreBlobCreate:'restoreBlobGet',restoreTreeCreate:'restoreTreeGet',restoreCommitCreate:'restoreCommitGet',restoreRefCreate:'restoreRefGet'}[state.stage];
  restoreCheck(stage,'ambiguous_stage');return nextRestore({...state,stage,restoreAmbiguousObject:true},api);
}
function restoreVerifiedRead(state){const {restoreReconcileKey,restoreReconcileAttempt,...verified}=state;return verified;}
function reconcileRestoreRead(state,now,api){
  const ref=state.stage==='restoreRefGet',sha=state.stage==='restoreBlobGet'?state.restoreObjectSha:state.stage==='restoreTreeGet'?state.restoreTreeSha:state.restoreCommitSha;
  const key=state.stage+':'+sha+(ref?':'+state.restoreManifestHash:''),attempt=state.restoreReconcileKey===key?state.restoreReconcileAttempt:0;
  const pending=()=>api.fail({...state,restoreStatus:'pending_reconciliation'},'restore_object_ambiguous');
  const matching=ref?state.restoreRefIntent===true:state.restoreObjectIntent===sha;
  if(!matching||!restoreSha(sha)||ref&&!/^[a-f0-9]{64}$/.test(state.restoreManifestHash||'')||!Number.isInteger(attempt)||attempt<0||attempt>=3||!Number.isFinite(state.deadline))return pending();
  const delay=2**attempt;
  if(!Number.isFinite(now)||now+delay*1000>=state.deadline)return pending();
  const path=ref?'/git/ref/heads/n8n-cache-restore/'+state.restoreManifestHash:'/git/'+({restoreBlobGet:'blobs',restoreTreeGet:'trees',restoreCommitGet:'commits'})[state.stage]+'/'+sha;
  return api.request({...state,restoreReconcileKey:key,restoreReconcileAttempt:attempt+1},state.stage,'github','GET',RESTORE_REPO+path,undefined,delay);
}
function advanceRestore(state,response,now,api){
  const body=response.body,status=response.statusCode;
  if(status===404&&['restoreBlobGet','restoreTreeGet','restoreCommitGet','restoreRefGet'].includes(state.stage)){
    if(state.restoreAmbiguousObject||state.restoreObjectIntent===state.restoreObjectSha&&state.stage==='restoreBlobGet'||state.restoreObjectIntent===state.restoreTreeSha&&state.stage==='restoreTreeGet'||state.restoreObjectIntent===state.restoreCommitSha&&state.stage==='restoreCommitGet'||state.restoreRefIntent&&state.stage==='restoreRefGet')return reconcileRestoreRead(state,now,api);
    const stage=state.stage.replace('Get','Create'),sha=state.stage==='restoreTreeGet'?state.restoreTreeSha:state.stage==='restoreCommitGet'?state.restoreCommitSha:state.restoreObjectSha;
    return api.checkpoint({...state,restoreObjectIntent:sha,...(state.stage==='restoreRefGet'?{restoreRefIntent:true}:{})},stage);
  }
  switch(state.stage){
    case 'restoreIndexRef':
      restoreCheck(body?.object?.type==='commit'&&restoreSha(body.object.sha),'inventory_ref');
      return api.request({...state,restoreInventoryRef:body.object.sha},'restoreIndex','github','GET',`${RESTORE_REPO}/contents/operations/days?ref=${body.object.sha}`);
    case 'restoreIndex':{
      if(status===404)return restoreMissingCandidate(state,api);
      restoreCheck(Array.isArray(body)&&body.length<1000&&Buffer.byteLength(JSON.stringify(body))<=1048576,'inventory_bounds');
      const dates=body.map(entry=>{restoreCheck(entry?.type==='file'&&/^\d{4}-\d{2}-\d{2}\.json$/.test(entry.name||'')&&entry.path==='operations/days/'+entry.name,'inventory_entry');const date=entry.name.slice(0,-5);restoreCheck(new Date(date+'T00:00:00Z').toISOString().slice(0,10)===date,'inventory_date');return date;});
      restoreCheck(new Set(dates).size===dates.length,'inventory_duplicate');
      const candidates=dates.filter(date=>date<state.marketDate).sort().reverse().slice(0,35);
      if(!candidates.length)return restoreMissingCandidate(state,api);
      return restoreCandidate({...state,restoreCandidates:candidates,restoreCandidateCursor:0,restoreCacheCandidateDate:candidates[0]},api);
    }
    case 'restoreState':{
      if(status===404)return restoreMissingCandidate(state,api);
      restoreCheck(typeof body?.content==='string'&&body.content.length<=3000000,'prior_size');const day=JSON.parse(Buffer.from(body.content,'base64').toString('utf8')),p=cacheCustodyForDay(day,state.restoreCacheCandidateDate||state.previousSessionDate)||day;
      if(!Object.prototype.hasOwnProperty.call(p,'cacheActiveManifestHash')&&!Object.prototype.hasOwnProperty.call(p,'cacheManifestHash')&&p.cacheStatus!=='verified')return restoreMissingCandidate(state,api);
      validatePrior(p,state);
      return api.request({...state,restorePrior:p,restoreFileMeta:p.cacheFileMeta,restorePageId:p.pageId,restoreManifestHash:p.cacheManifestHash},'restorePage','notion','GET',`${RESTORE_NOTION}/pages/${p.pageId}`);
    }
    case 'restorePage':{
      const p=state.restorePrior;
      restoreCheck(body?.id===p.pageId&&restoreProp(body.properties,'Cache Status')==='complete'&&restoreProp(body.properties,'Cache Active Revision')===p.cacheManifestHash&&restoreProp(body.properties,'Cache Manifest Hash')===p.cacheManifestHash&&restoreProp(body.properties,'Cache Proof Hash')===p.cacheProofHash&&restoreProp(body.properties,'Cache Artifact ID')===p.cacheArtifactId,'page_custody');
      return restoreChildren({...state,restoreChildren:[],restoreChildrenPages:0,restoreChildrenCursor:undefined},api);
    }
    case 'restoreChildren':{
      restoreCheck(Array.isArray(body?.results)&&(state.restoreChildrenPages||0)<10,'children_bounds');
      const updated={...state,restoreChildren:[...state.restoreChildren,...body.results.filter(b=>b.type==='file').map(b=>({id:b.id,type:b.type,file:{caption:b.file?.caption}}))],restoreChildrenPages:state.restoreChildrenPages+1};
      if(body.has_more){restoreCheck(typeof body.next_cursor==='string','cursor');return restoreChildren({...updated,restoreChildrenCursor:body.next_cursor},api);}
      const ids=Object.fromEntries(updated.restoreFileMeta.map(e=>{const matches=updated.restoreChildren.filter(b=>restoreCaption(b)===`Market cache ${state.restoreManifestHash} ${e.name} ${e.sha256}`);restoreCheck(matches.length===1&&restoreUuid(matches[0].id),'attachment_custody');return [e.name,matches[0].id];}));
      return restoreGetPart({...updated,restoreBlockIds:ids,restoreCursor:0,restoreTransient:{files:{}}},api);
    }
    case 'restoreFile':{
      const e=state.restoreFileMeta[state.restoreCursor],id=state.restoreBlockIds[e.name];
      restoreCheck(body?.id===id&&body.parent?.page_id===state.restorePageId&&body.type==='file'&&body.file?.type==='file'&&restoreCaption(body)===`Market cache ${state.restoreManifestHash} ${e.name} ${e.sha256}`,'file_custody');
      marketCache.validateCacheDownload(body.file.file,{authentication:'none',followRedirects:false,responseFormat:'file'},new Date(now).toISOString());
      return api.request(state,'restoreDownload','cacheDownload','GET',body.file.file.url);
    }
    case 'restoreDownload':{
      const e=state.restoreFileMeta[state.restoreCursor];restoreCheck(typeof body?.bytes==='string','binary');const bytes=Buffer.from(body.bytes,'base64');restoreCheck(bytes.length===e.bytes&&restoreHash(bytes)===e.sha256,'file_hash');
      const updated={...state,restoreCursor:state.restoreCursor+1,restoreTransient:{files:{...state.restoreTransient.files,[e.name]:body.bytes}}};
      if(updated.restoreCursor<updated.restoreFileMeta.length)return restoreGetPart(updated,api);
      return api.checkpoint({...prepareRestoreDescriptor(updated,now),restoreStatus:'git_staging'},'restoreBlobGet');
    }
    case 'restoreBlobCreate':restoreCheck(body?.sha===state.restoreObjectSha,'blob_sha');return nextRestore({...state,stage:'restoreBlobGet',restoreAmbiguousObject:false},api);
    case 'restoreBlobGet':{
      const bytes=Buffer.from(state.restoreTransient.files[state.restoreGitFiles[state.restoreBlobCursor]],'base64');
      restoreCheck(body?.sha===state.restoreObjectSha&&body.encoding==='base64'&&body.size===bytes.length&&gitObject('blob',Buffer.from(body.content||'','base64'))===state.restoreObjectSha,'blob_readback');
      return api.checkpoint({...restoreVerifiedRead(state),restoreBlobCursor:state.restoreBlobCursor+1,restoreObjectIntent:state.restoreObjectIntent===state.restoreObjectSha?undefined:state.restoreObjectIntent,restoreAmbiguousObject:false},'restoreBlobGet');
    }
    case 'restoreTreeCreate':restoreCheck(body?.sha===state.restoreTreeSha,'tree_sha');return nextRestore({...state,stage:'restoreTreeGet',restoreAmbiguousObject:false},api);
    case 'restoreTreeGet':{
      const entries=body?.tree?.map(({path,mode,type,sha})=>({path,mode,type,sha}));
      restoreCheck(body?.sha===state.restoreTreeSha&&body.truncated===false&&JSON.stringify(entries)===JSON.stringify(state.restoreTreeEntries),'tree_readback');
      return api.checkpoint({...restoreVerifiedRead(state),restoreObjectIntent:undefined,restoreAmbiguousObject:false},'restoreCommitGet');
    }
    case 'restoreCommitCreate':restoreCheck(body?.sha===state.restoreCommitSha,'commit_sha');return nextRestore({...state,stage:'restoreCommitGet',restoreAmbiguousObject:false},api);
    case 'restoreCommitGet':{
      const expected=state.restoreCommitBody;
      restoreCheck(body?.sha===state.restoreCommitSha&&body.tree?.sha===state.restoreTreeSha&&Array.isArray(body.parents)&&body.parents.length===0&&(body.message===expected.message||expected.message.endsWith('\n')&&body.message===expected.message.slice(0,-1))&&['author','committer'].every(k=>['name','email'].every(v=>body[k]?.[v]===expected[k][v])&&Date.parse(body[k]?.date)===Date.parse(expected[k].date)),'commit_readback');
      return api.checkpoint({...restoreVerifiedRead(state),restoreObjectIntent:undefined,restoreAmbiguousObject:false},'restoreRefGet');
    }
    case 'restoreRefCreate':return nextRestore({...state,stage:'restoreRefGet',restoreAmbiguousObject:false},api);
    case 'restoreRefGet':
      restoreCheck(body?.ref==='refs/heads/n8n-cache-restore/'+state.restoreManifestHash&&body.object?.type==='commit'&&body.object.sha===state.restoreCommitSha,'immutable_ref');
      return api.checkpoint({...restoreVerifiedRead(state),restoreStatus:'verified',dispatchIntent:true,restoreObjectIntent:undefined,restoreRefIntent:undefined,restoreAmbiguousObject:false},'dispatch');
    default:throw Error('restore_unknown_stage');
  }
}
module.exports={beginRestore,advanceRestore,nextRestore,ambiguousRestore,prepareRestoreDescriptor,restoreDurable,restoreDispatchInputs,gitObject,captureVerifiedCache,cacheCustodyForDay};
