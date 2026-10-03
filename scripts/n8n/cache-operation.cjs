'use strict';

// Credential-free transitions. The host owns credentials, CAS, deadlines and
// throttling. Transient bytes never belong in the durable writer checkpoint.
const {createHash}=require('crypto');
const marketCache=require('./market-cache.cjs');
const CACHE_REPO='https://api.github.com/repos/pingpongtech-uskg/stock-web-pages';
const CACHE_NOTION='https://api.notion.com/v1';
const cacheHash=bytes=>createHash('sha256').update(bytes).digest('hex');
const cacheCheck=(ok,reason)=>{if(!ok)throw Error('cache_'+reason);};
const cacheText=value=>[{type:'text',text:{content:String(value)}}];
const cacheUuid=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
const cacheEntry=state=>state.cacheEntries[state.cacheCursor||0];
const cacheSource=state=>({requestId:state.requestId,actionsRunId:state.actionsRunId,sourceGitCommit:state.runHeadSha});
const CACHE_FIELDS={'Cache Status':{rich_text:{}},'Cache Manifest Hash':{rich_text:{}},'Cache Artifact ID':{rich_text:{}},'Cache Proof Hash':{rich_text:{}},'Cache Active Revision':{rich_text:{}},'Cache Metrics Complete':{checkbox:{}},'Cache Previous Trading Date':{date:{}},'Cache Verification Level':{rich_text:{}},'Cache Parts Expected':{number:{}},'Cache Parts Verified':{number:{}}};

function cacheDurable(state){
  const {cacheTransient,cacheEntries,cacheSignedUrl,cacheRoster,cacheChildren,...safe}=state;
  return safe;
}
function beginCache(state,api){
  cacheCheck(/^\d{1,24}$/.test(state.actionsRunId||'')&&/^[a-f0-9]{40}$/.test(state.runHeadSha||''),'run_context');
  return api.request({...state,cacheStatus:'pending',cacheZipVerifiedHash:undefined},'cacheRun','github','GET',`${CACHE_REPO}/actions/runs/${state.actionsRunId}`);
}
function cacheContents(state,stage,name,api){
  cacheCheck(/^[a-f0-9]{40}$/.test(state.publication?.publishedGitCommit||''),'published_commit');
  return api.request(state,stage,'github','GET',`${CACHE_REPO}/contents/public/data/${name}?ref=${state.publication.publishedGitCommit}`);
}
function cacheContentBytes(body,maxBytes=1048576){
  cacheCheck(body?.encoding==='base64'&&typeof body.content==='string'&&Number.isSafeInteger(body.size)&&body.size>0&&body.size<=maxBytes,'contents');
  const bytes=Buffer.from(body.content,'base64');cacheCheck(bytes.length===body.size,'contents');return bytes;
}
function cacheChildrenRequest(state,api){
  cacheCheck(cacheUuid(state.pageId),'page');
  return api.request(state,'cacheChildren','notion','GET',`${CACHE_NOTION}/blocks/${state.pageId}/children?page_size=100${state.cacheChildrenCursor?'&start_cursor='+encodeURIComponent(state.cacheChildrenCursor):''}`);
}
function readCacheArtifact(state,body,api){
  cacheCheck(state.cacheZipVerifiedHash===state.cacheArtifactSha256&&/^[a-f0-9]{64}$/.test(state.cacheZipVerifiedHash||''),'zip_custody');
  cacheCheck(body?.files&&typeof body.files==='object','artifact_files');
  const files=Object.fromEntries(Object.entries(body.files).map(([name,data])=>{cacheCheck(typeof data==='string','artifact_files');return [name,Buffer.from(data,'base64')];}));
  for(const name of ['manifest.json','proof.json','expected.json'])cacheCheck(files[name]?.length>0&&files[name].length<=1048576,'envelope_size');
  const manifest=JSON.parse(files['manifest.json'].toString('utf8')),expected=JSON.parse(files['expected.json'].toString('utf8'));
  cacheCheck(manifest.marketDate===state.marketDate&&expected.marketDate===state.marketDate&&['requestId','actionsRunId','sourceGitCommit'].every(key=>expected.source?.[key]===cacheSource(state)[key]),'expected_lineage');
  const stockGroup=expected.groups?.find(group=>group.kind==='published_stock_inputs');
  cacheCheck(stockGroup?.sourceSha256===state.cacheLatestHash&&JSON.stringify(stockGroup.codes)===JSON.stringify(state.cacheRoster),'published_roster');
  const names=manifest.groups.flatMap(group=>group.shards.map(part=>part.name));
  cacheCheck(JSON.stringify(Object.keys(files).sort())===JSON.stringify(['manifest.json','proof.json','expected.json',...names].sort()),'artifact_members');
  const proofHash=cacheHash(files['proof.json']);
  const proof=marketCache.verifyCompressedMarketCache(manifest,Object.fromEntries(names.map(name=>[name,files[name]])),{...expected,manifestHash:manifest.manifestHash,producerProofSha256:proofHash,artifactLineage:{repository:'pingpongtech-uskg/stock-web-pages',workflowId:state.cacheRunWorkflowId,artifactId:state.cacheArtifactId,artifactSha256:state.cacheArtifactSha256,...cacheSource(state)}},files['proof.json']);
  const entries=Object.keys(files).sort().map(name=>({name,filename:name.endsWith('.gz')?name:`${state.marketDate}.${manifest.manifestHash.slice(0,12)}.${name}`,sha256:cacheHash(files[name]),bytes:files[name].length,marker:`Market cache ${manifest.manifestHash} ${name} ${cacheHash(files[name])}`}));
  return cacheChildrenRequest({...state,cacheStatus:'uploading',cacheManifestHash:manifest.manifestHash,cacheProofHash:proofHash,cachePreviousTradingDate:manifest.previousTradingDate,cacheMetricsComplete:proof.metricsComplete,cacheIndependentRawSemanticsVerified:false,cacheRawSemanticsVerifiedByProducer:true,cachePartsExpected:entries.length,cacheFileMeta:entries.map(({name,sha256,bytes})=>({name,sha256,bytes})),cacheEntries:entries,cacheTransient:{files:body.files},cacheCursor:0,cacheVerifiedFiles:[],cacheChildren:[],cacheChildrenCursor:undefined,cacheChildrenPages:0},api);
}
function selectCachePart(state,api){
  if((state.cacheCursor||0)>=state.cacheEntries.length)return promoteCache(state,api);
  const entry=cacheEntry(state),matches=(state.cacheChildren||[]).filter(block=>block.type==='file'&&block.file?.caption?.map(part=>part.plain_text||part.text?.content||'').join('')===entry.marker);
  cacheCheck(matches.length<=1,'duplicate_attachment');
  if(matches.length)return api.request({...state,cacheBlockId:matches[0].id},'cacheGetFile','notion','GET',`${CACHE_NOTION}/blocks/${matches[0].id}`);
  if(state.cacheUploadIntent){
    if(state.cacheUploadIntent!==entry.name||(state.cacheUploadManifestHash&&state.cacheUploadManifestHash!==state.cacheManifestHash))return api.fail({...state,cacheStatus:'pending_reconciliation'},'cache_pending_upload_other_part');
    if(state.cacheAppendAmbiguous||state.cacheAppendAttempted)return api.fail({...state,cacheStatus:'pending_reconciliation'},'cache_attachment_ambiguous');
    if(!cacheUuid(state.cacheUploadId))return api.fail({...state,cacheStatus:'pending_reconciliation'},'cache_upload_create_ambiguous');
    return api.request(state,'cacheUploadStatus','notion','GET',`${CACHE_NOTION}/file_uploads/${state.cacheUploadId}`);
  }
  if(state.cacheAppendAmbiguous||state.cacheAppendAttempted)return api.fail({...state,cacheStatus:'pending_reconciliation'},'cache_attachment_ambiguous');
  return api.checkpoint({...state,cacheUploadId:undefined,cacheUploadIntent:entry.name,cacheUploadManifestHash:state.cacheManifestHash,cacheUploadSent:false,cacheSendAmbiguous:false},'cacheCreateUpload');
}
function promoteCache(state,api){
  cacheCheck(state.cacheEntries?.length>0&&state.cacheEntries.every(entry=>state.cacheVerifiedFiles?.includes(entry.name))&&new Set(state.cacheVerifiedFiles).size===state.cacheEntries.length,'readback_incomplete');
  return api.request(state,'cachePromote','notion','PATCH',`${CACHE_NOTION}/pages/${state.pageId}`,{properties:{'Cache Status':{rich_text:cacheText('complete')},'Cache Manifest Hash':{rich_text:cacheText(state.cacheManifestHash)},'Cache Active Revision':{rich_text:cacheText(state.cacheManifestHash)},'Cache Artifact ID':{rich_text:cacheText(state.cacheArtifactId||'')},'Cache Proof Hash':{rich_text:cacheText(state.cacheProofHash||'')},'Cache Metrics Complete':{checkbox:state.cacheMetricsComplete===true},'Cache Previous Trading Date':{date:{start:state.cachePreviousTradingDate}},'Cache Verification Level':{rich_text:cacheText('compressed_backup_verified')},'Cache Parts Expected':{number:state.cacheEntries.length},'Cache Parts Verified':{number:state.cacheVerifiedFiles.length}}});
}
function ambiguousCacheWrite(state,api){
  if(state.stage==='cacheAppend')return cacheChildrenRequest({...state,cacheAppendAmbiguous:true,cacheChildren:[],cacheChildrenCursor:undefined,cacheChildrenPages:0},api);
  if(state.stage==='cacheSendUpload')return api.request({...state,cacheSendAmbiguous:true},'cacheUploadStatus','notion','GET',`${CACHE_NOTION}/file_uploads/${state.cacheUploadId}`);
  return api.fail({...state,cacheStatus:'failed'},'cache_upload_create_ambiguous');
}
function nextCache(state,api){
  switch(state.stage){
    case 'cacheRun':return beginCache(state,api);
    case 'cacheGetFile':cacheCheck(cacheUuid(state.cacheBlockId),'file_block');return api.request(state,'cacheGetFile','notion','GET',`${CACHE_NOTION}/blocks/${state.cacheBlockId}`);
    case 'cacheCreateUpload':return api.request(state,'cacheCreateUpload','notion','POST',`${CACHE_NOTION}/file_uploads`,{mode:'single_part',filename:cacheEntry(state).filename,content_type:cacheEntry(state).name.endsWith('.gz')?'application/gzip':'application/json'});
    case 'cacheSendUpload':if(!state.cacheSendAttempted)return api.checkpoint({...state,cacheSendAttempted:true},'cacheSendUpload');return api.request(state,'cacheSendUpload','cacheUpload','POST',`${CACHE_NOTION}/file_uploads/${state.cacheUploadId}/send`);
    case 'cacheAppend':if(!state.cacheAppendAttempted)return api.checkpoint({...state,cacheAppendAttempted:true},'cacheAppend');return api.request(state,'cacheAppend','notion','PATCH',`${CACHE_NOTION}/blocks/${state.pageId}/children`,{children:[{object:'block',type:'file',file:{type:'file_upload',file_upload:{id:state.cacheUploadId},caption:cacheText(cacheEntry(state).marker)}}]});
    case 'cacheContinue':return selectCachePart(state,api);
    default:throw Error('cache_unknown_next');
  }
}
function cachePropertiesMatch(actual,expected){
  return Object.entries(expected).every(([name,value])=>{
    const type=Object.keys(value)[0],property=actual?.[name];
    if(type==='rich_text')return property?.rich_text?.map(part=>part.plain_text||part.text?.content||'').join('')===value.rich_text.map(part=>part.text.content).join('');
    if(type==='date')return property?.date?.start===value.date.start;
    return property?.[type]===value[type];
  });
}
const CACHE_CRC_TABLE=Object.freeze(Array.from({length:256},(_,index)=>{let value=index;for(let bit=0;bit<8;bit++)value=(value>>>1)^((value&1)?0xedb88320:0);return value>>>0;}));
function cacheCrc(bytes){let crc=0xffffffff;for(const byte of bytes)crc=(crc>>>8)^CACHE_CRC_TABLE[(crc^byte)&255];return (crc^0xffffffff)>>>0;}
function cacheZipMembers(bytes,state){
  cacheCheck(Buffer.isBuffer(bytes)&&bytes.length>=22&&bytes.length<=68*1024*1024&&bytes.length===state.cacheArtifactBytes,'zip_size');
  cacheCheck(cacheHash(bytes)===state.cacheArtifactSha256,'zip_hash');
  let end=-1;
  for(let index=bytes.length-22;index>=Math.max(0,bytes.length-65557);index--)if(bytes.readUInt32LE(index)===0x06054b50&&index+22+bytes.readUInt16LE(index+20)===bytes.length){end=index;break;}
  cacheCheck(end>=0&&bytes.readUInt16LE(end+4)===0&&bytes.readUInt16LE(end+6)===0,'zip_directory');
  const count=bytes.readUInt16LE(end+10),centralSize=bytes.readUInt32LE(end+12),centralOffset=bytes.readUInt32LE(end+16);
  cacheCheck(count>=3&&count<=259&&bytes.readUInt16LE(end+8)===count&&centralOffset+centralSize===end,'zip_directory');
  let cursor=centralOffset,total=0;const names=[],members=[];
  for(let index=0;index<count;index++){
    cacheCheck(cursor+46<=end&&bytes.readUInt32LE(cursor)===0x02014b50,'zip_directory');
    const crc=bytes.readUInt32LE(cursor+16),flags=bytes.readUInt16LE(cursor+8),method=bytes.readUInt16LE(cursor+10),compressed=bytes.readUInt32LE(cursor+20),expanded=bytes.readUInt32LE(cursor+24),nameSize=bytes.readUInt16LE(cursor+28),extra=bytes.readUInt16LE(cursor+30),comment=bytes.readUInt16LE(cursor+32),attributes=bytes.readUInt32LE(cursor+38),local=bytes.readUInt32LE(cursor+42);
    cacheCheck(cursor+46+nameSize+extra+comment<=end&&nameSize>0&&nameSize<=180,'zip_directory');
    const name=bytes.subarray(cursor+46,cursor+46+nameSize).toString('utf8');
    cacheCheck(/^(?:manifest\.json|proof\.json|expected\.json|\d{4}-\d{2}-\d{2}\.[a-zA-Z0-9_-]+\.\d+\.[a-f0-9]{64}\.json\.gz)$/.test(name)&&!names.includes(name),'zip_member');
    cacheCheck((flags&~0x808)===0&&method===0&&[0,0x8000].includes((attributes>>>16)&0xf000)&&bytes.readUInt16LE(cursor+34)===0,'zip_member');
    cacheCheck(compressed===expanded&&expanded>0&&expanded<=(name.endsWith('.gz')?4*1024*1024:1048576)&&compressed>0,'zip_expansion');
    cacheCheck(local+30<=centralOffset&&bytes.readUInt32LE(local)===0x04034b50&&bytes.readUInt16LE(local+6)===flags&&bytes.readUInt16LE(local+8)===method,'zip_local');
    const localName=bytes.readUInt16LE(local+26),localExtra=bytes.readUInt16LE(local+28);
    const dataOffset=local+30+localName+localExtra,dataEnd=dataOffset+compressed;
    cacheCheck(dataEnd<=centralOffset&&bytes.subarray(local+30,local+30+localName).toString('utf8')===name,'zip_local');
    for(const [start,length]of [[cursor+46+nameSize,extra],[local+30+localName,localExtra]]){
      let at=start;while(at<start+length){cacheCheck(at+4<=start+length,'zip_extra');const type=bytes.readUInt16LE(at),size=bytes.readUInt16LE(at+2);cacheCheck(type!==1&&at+4+size<=start+length,'zip_extra');at+=4+size;}
    }
    const localCrc=bytes.readUInt32LE(local+14),localCompressed=bytes.readUInt32LE(local+18),localExpanded=bytes.readUInt32LE(local+22);
    let endOffset=dataEnd;
    if(flags&8){
      cacheCheck([0,crc].includes(localCrc)&&[0,compressed].includes(localCompressed)&&[0,expanded].includes(localExpanded)&&dataEnd+12<=centralOffset,'zip_descriptor');
      const descriptor=dataEnd+(bytes.readUInt32LE(dataEnd)===0x08074b50?4:0);
      cacheCheck(descriptor+12<=centralOffset&&bytes.readUInt32LE(descriptor)===crc&&bytes.readUInt32LE(descriptor+4)===compressed&&bytes.readUInt32LE(descriptor+8)===expanded,'zip_descriptor');endOffset=descriptor+12;
    }else cacheCheck(localCrc===crc&&localCompressed===compressed&&localExpanded===expanded,'zip_local');
    cacheCheck(cacheCrc(bytes.subarray(dataOffset,dataEnd))===crc,'zip_crc');
    names.push(name);members.push({name,local,dataOffset,bytes:compressed,endOffset});total+=expanded;cursor+=46+nameSize+extra+comment;
  }
  cacheCheck(cursor===end&&total<=67*1024*1024&&['manifest.json','proof.json','expected.json'].every(name=>names.includes(name)),'zip_expansion');
  const ordered=[...members].sort((a,b)=>a.local-b.local);cacheCheck(ordered[0].local===0&&ordered.every((entry,index)=>entry.endOffset===(ordered[index+1]?.local??centralOffset)),'zip_overlap');
  return members;
}
function validateCacheZip(bytes,state){return cacheZipMembers(bytes,state).map(member=>member.name);}
function extractStoredCacheZip(bytes,state){return Object.fromEntries(cacheZipMembers(bytes,state).map(member=>[member.name,bytes.subarray(member.dataOffset,member.dataOffset+member.bytes)]));}
function advanceCache(state,response,now,api){
  const body=response.body;
  switch(state.stage){
    case 'cacheRun':
      cacheCheck(String(body?.id)===state.actionsRunId&&body.head_sha===state.runHeadSha&&body.path==='.github/workflows/daily.yml'&&body.head_branch==='main'&&body.event==='workflow_dispatch'&&/^\d{1,20}$/.test(String(body.workflow_id))&&body.status==='completed'&&body.conclusion==='success'&&body.display_title===`Daily screening | ${state.requestId} | ${state.marketDate}`,'run_lineage');
      return cacheContents({...state,cacheRunWorkflowId:String(body.workflow_id)},'cacheFingerprint','publication.json',api);
    case 'cacheFingerprint':{
      const fingerprint=JSON.parse(cacheContentBytes(body).toString('utf8'));
      cacheCheck(fingerprint.schemaVersion==='publication-fingerprint-v1'&&fingerprint.marketDate===state.marketDate&&fingerprint.runId===state.runId&&/^[a-f0-9]{64}$/.test(fingerprint.contentHash),'fingerprint');
      return cacheContents({...state,cacheLatestHash:fingerprint.contentHash},'cacheLatest','latest.json',api);
    }
    case 'cacheLatest':{
      const raw=cacheContentBytes(body,16*1024*1024);cacheCheck(cacheHash(raw)===state.cacheLatestHash,'latest_hash');const latest=JSON.parse(raw.toString('utf8'));
      cacheCheck(latest.marketDate===state.marketDate&&latest.runId===state.runId&&Array.isArray(latest.stocks)&&latest.stocks.length>0&&latest.stocks.length<=1000,'latest');
      const roster=latest.stocks.map(stock=>stock.code).sort();cacheCheck(new Set(roster).size===roster.length&&roster.every(code=>/^\d{4,6}[A-Z]?$/.test(code)),'roster');
      return api.request({...state,cacheRoster:roster},'cacheArtifacts','github','GET',`${CACHE_REPO}/actions/runs/${state.actionsRunId}/artifacts?per_page=100`);
    }
    case 'cacheArtifacts':{
      const matches=body.artifacts?.filter(item=>item.name==='market-cache'&&item.expired===false);cacheCheck(matches?.length===1,'artifact_missing_or_ambiguous');const item=matches[0];
      cacheCheck(/^\d{1,20}$/.test(String(item.id))&&Number.isSafeInteger(item.size_in_bytes)&&item.size_in_bytes>0&&item.size_in_bytes<=68*1024*1024&&/^sha256:[a-f0-9]{64}$/.test(item.digest||''),'artifact_metadata');
      cacheCheck(!item.workflow_run||(String(item.workflow_run.id)===state.actionsRunId&&item.workflow_run.head_sha===state.runHeadSha),'artifact_lineage');
      return api.request({...state,cacheArtifactId:String(item.id),cacheArtifactSha256:item.digest.slice(7),cacheArtifactBytes:item.size_in_bytes},'cacheRedirect','github','GET',`${CACHE_REPO}/actions/artifacts/${item.id}/zip`);
    }
    case 'cacheRedirect':{
      const location=response.headers?.location||response.headers?.Location;
      cacheCheck(response.statusCode===302&&typeof location==='string'&&location.length<=16384&&/^https:\/\/[a-zA-Z0-9.-]+\.(blob\.core\.windows\.net|actions\.githubusercontent\.com|githubusercontent\.com)\/[^\s#]+$/.test(location),'artifact_redirect');
      return api.request(state,'cacheZip','cacheZip','GET',location);
    }
    case 'cacheArtifactBytes':return readCacheArtifact(state,body,api);
    case 'cacheChildren':{
      cacheCheck(Array.isArray(body?.results)&&(state.cacheChildrenPages||0)<10,'children_limit');
      const updated={...state,cacheChildren:[...(state.cacheChildren||[]),...body.results.filter(block=>block.type==='file').map(block=>({id:block.id,type:block.type,file:{caption:block.file?.caption}}))],cacheChildrenPages:(state.cacheChildrenPages||0)+1};
      if(body.has_more){cacheCheck(typeof body.next_cursor==='string','children_cursor');return cacheChildrenRequest({...updated,cacheChildrenCursor:body.next_cursor},api);}
      return selectCachePart({...updated,cacheChildrenCursor:undefined},api);
    }
    case 'cacheCreateUpload':
      cacheCheck(cacheUuid(body?.id)&&body.status==='pending','upload_created');
      return api.checkpoint({...state,cacheUploadId:body.id},'cacheSendUpload');
    case 'cacheSendUpload':
    case 'cacheUploadStatus':
      cacheCheck(body?.id===state.cacheUploadId,'upload_identity');
      if(body.status==='pending'&&state.stage==='cacheUploadStatus'&&!state.cacheSendAmbiguous&&!state.cacheSendAttempted&&!state.cacheUploadSent)return api.checkpoint(state,'cacheSendUpload');
      if(body.status!=='uploaded')return api.fail({...state,cacheStatus:'pending_reconciliation'},'cache_upload_send_ambiguous');
      return api.checkpoint({...state,cacheUploadSent:true},'cacheAppend');
    case 'cacheAppend':return cacheChildrenRequest({...state,cacheChildren:[],cacheChildrenCursor:undefined,cacheChildrenPages:0},api);
    case 'cacheGetFile':{
      const entry=cacheEntry(state);
      cacheCheck(body?.id===state.cacheBlockId&&body.parent?.page_id===state.pageId&&body.type==='file'&&body.file?.type==='file'&&body.file.caption?.map(part=>part.plain_text||part.text?.content||'').join('')===entry.marker,'file_block');
      marketCache.validateCacheDownload(body.file.file,{authentication:'none',followRedirects:false,responseFormat:'file'},new Date(now).toISOString());
      return api.request(state,'cacheDownload','cacheDownload','GET',body.file.file.url);
    }
    case 'cacheDownload':{
      const entry=cacheEntry(state);cacheCheck(typeof body?.bytes==='string','readback_binary');const bytes=Buffer.from(body.bytes,'base64');
      cacheCheck(bytes.length===entry.bytes&&cacheHash(bytes)===entry.sha256,'readback_hash');
      const clear=entry.name===state.cacheUploadIntent?{cacheUploadId:undefined,cacheUploadIntent:undefined,cacheUploadManifestHash:undefined,cacheAppendAmbiguous:false,cacheAppendAttempted:false,cacheSendAmbiguous:false,cacheSendAttempted:false,cacheUploadSent:false}:{};
      return api.checkpoint({...state,...clear,cacheVerifiedFiles:[...new Set([...(state.cacheVerifiedFiles||[]),entry.name])],cacheBlockIds:{...(state.cacheBlockIds||{}),[entry.name]:state.cacheBlockId},cacheCursor:(state.cacheCursor||0)+1,cacheBlockId:undefined},'cacheContinue');
    }
    case 'cachePromote':return api.request(state,'cacheVerifyPage','notion','GET',`${CACHE_NOTION}/pages/${state.pageId}`);
    case 'cacheVerifyPage':{
      cacheCheck(body?.id===state.pageId&&cachePropertiesMatch(body.properties,promoteCache(state,api).op.body.properties),'metadata_readback');
      return api.checkpoint({...state,cacheStatus:'verified',cacheActiveManifestHash:state.cacheManifestHash,cachePartsVerified:state.cacheVerifiedFiles.length},'summaryRead');
    }
    default:throw Error('cache_unknown_stage');
  }
}
module.exports={beginCache,advanceCache,ambiguousCacheWrite,cacheDurable,promoteCache,nextCache,validateCacheZip,extractStoredCacheZip,CACHE_FIELDS};
