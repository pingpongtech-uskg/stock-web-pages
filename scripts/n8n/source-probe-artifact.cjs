// Authenticated Actions artifacts are source evidence only; never a screened release.
const PROBE_ERRORS=['token_missing','budget_exhausted','source_blocked','quota_unavailable','transport_unavailable','invalid_source_rows','operation_limit','official_source_unavailable','official_source_invalid','checkpoint_unavailable'];
const PROBE_OFFICIAL='https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading';
function probeAssert(condition){if(!condition)throw Error('probe_artifact_schema');}
function probeInt(value,min=0,max=Number.MAX_SAFE_INTEGER){return Number.isSafeInteger(value)&&value>=min&&value<=max;}
function probeDate(value){return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&!Number.isNaN(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;}
function probeKeys(value,required,optional=[]){probeAssert(value&&typeof value==='object'&&!Array.isArray(value));probeAssert(required.every(key=>Object.hasOwn(value,key))&&Object.keys(value).every(key=>[...required,...optional].includes(key)));}
function probeError(value){probeAssert(value===null||PROBE_ERRORS.includes(value));}
const PROBE_LEGACY_QUOTA=['dailyAttempts','projectCeiling','accountWindowCeiling'];
const PROBE_HOURLY_QUOTA=['quotaPolicy','rollingHourAttempts','projectHourlyCap','accountAllowanceRemaining','quotaObservedAt'];
function probeUtc(value){return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)&&!Number.isNaN(Date.parse(value))&&new Date(value).toISOString().slice(0,19)===value.slice(0,19);}
function sourceValidateQuota(summary){
 if(Object.hasOwn(summary,'quotaPolicy')){
  probeAssert(summary.quotaPolicy==='rolling-hour-v1'&&PROBE_HOURLY_QUOTA.every(key=>Object.hasOwn(summary,key))&&!PROBE_LEGACY_QUOTA.some(key=>Object.hasOwn(summary,key)));
  if(summary.rollingHourAttempts===null){
   probeAssert(summary.outcome==='unavailable'&&Array.isArray(summary.cases)&&summary.cases.length===0&&summary.errorCategory==='checkpoint_unavailable'&&summary.actualAttempts===0&&summary.dataRequests===0&&summary.cacheHits===0&&summary.projectHourlyCap===300&&summary.accountAllowanceRemaining===null&&summary.quotaObservedAt===null);
  }else probeAssert(probeInt(summary.rollingHourAttempts,0,300)&&probeInt(summary.projectHourlyCap,1,300));
  probeAssert(summary.accountAllowanceRemaining===null||probeInt(summary.accountAllowanceRemaining));
  probeAssert(summary.quotaObservedAt===null||probeUtc(summary.quotaObservedAt));
 }else{
  // Historical v1 artifacts keep their observed daily fields; never reinterpret them as hourly state.
  probeAssert(!PROBE_HOURLY_QUOTA.some(key=>Object.hasOwn(summary,key)));
  for(const key of PROBE_LEGACY_QUOTA)if(Object.hasOwn(summary,key))probeAssert(summary[key]===null||probeInt(summary[key],0,key==='dailyAttempts'?300:Number.MAX_SAFE_INTEGER));
  if(Object.hasOwn(summary,'projectCeiling'))probeAssert(probeInt(summary.projectCeiling,1,300));
  if(summary.dailyAttempts!==undefined&&summary.dailyAttempts!==null)probeAssert(summary.dailyAttempts>=summary.actualAttempts);
 }
}
function sourceValidateCase(item,dates){
 probeKeys(item,['code','case','buy','sell','net','status','coverage','missingDates','errorCategory']);
 probeAssert(/^[1-9]\d{3}$/.test(item.code)&&['positive','negative','zero'].includes(item.case)&&probeInt(item.buy)&&probeInt(item.sell)&&Number.isSafeInteger(item.net)&&item.buy-item.sell===item.net);
 probeAssert(Math.sign(item.net)==={positive:1,negative:-1,zero:0}[item.case]);probeError(item.errorCategory);
 probeAssert(Array.isArray(item.missingDates)&&new Set(item.missingDates).size===item.missingDates.length&&item.missingDates.every((day,index)=>dates.includes(day)&&(!index||day>item.missingDates[index-1])));
 probeAssert(['complete','partial','unavailable'].includes(item.status)&&item.coverage===(11-item.missingDates.length)/11);
 probeAssert(item.status==='complete'?item.missingDates.length===0&&item.errorCategory===null:item.status==='partial'?item.missingDates.length>0&&item.errorCategory===null:item.missingDates.length===11&&item.errorCategory!==null);
 return {...item,missingDates:[...item.missingDates]};
}
function sourceValidateSummary(summary,state){
 probeKeys(summary,['probeVersion','marketDate','expectedDates','publicationEligible','globalCompleteness','tokenPresent','actualAttempts','dataRequests','cacheHits','accountLimit','observedRemaining','cases','outcome'],['errorCategory',...PROBE_LEGACY_QUOTA,...PROBE_HOURLY_QUOTA,'officialSourceUrl','officialRowCount','officialSha256']);
 const dates=summary.expectedDates;probeAssert(summary.probeVersion==='institutional-probe-v1'&&summary.marketDate===state.plan.marketDate&&summary.publicationEligible===false&&summary.globalCompleteness===false&&typeof summary.tokenPresent==='boolean');
 probeAssert(Array.isArray(dates)&&dates.length===11&&dates.every((day,index)=>probeDate(day)&&(!index||day>dates[index-1]))&&dates.at(-1)===state.plan.marketDate);
 probeAssert(probeInt(summary.actualAttempts,0,4)&&probeInt(summary.dataRequests,0,3)&&summary.actualAttempts>=summary.dataRequests&&summary.actualAttempts-summary.dataRequests<=1&&probeInt(summary.cacheHits,0,3)&&summary.cacheHits+summary.dataRequests<=3&&(!summary.dataRequests||summary.tokenPresent));
 probeAssert((summary.accountLimit===null||probeInt(summary.accountLimit,1))&&(summary.observedRemaining===null||probeInt(summary.observedRemaining))&&((summary.accountLimit===null)===(summary.observedRemaining===null))&&(summary.accountLimit===null||summary.observedRemaining<=summary.accountLimit));
 sourceValidateQuota(summary);
 if(Object.hasOwn(summary,'errorCategory'))probeError(summary.errorCategory);
 probeAssert(Array.isArray(summary.cases)&&[0,3].includes(summary.cases.length));const cases=summary.cases.map(item=>sourceValidateCase(item,dates));
 if(cases.length){probeAssert(new Set(cases.map(item=>item.code)).size===3&&cases.every((item,index)=>item.case===['positive','negative','zero'][index]));probeAssert((Object.hasOwn(summary,'quotaPolicy')?PROBE_HOURLY_QUOTA:PROBE_LEGACY_QUOTA).every(key=>Object.hasOwn(summary,key)));probeAssert(summary.officialSourceUrl===PROBE_OFFICIAL&&probeInt(summary.officialRowCount,3)&&/^[a-f0-9]{64}$/.test(summary.officialSha256||''));}
 else probeAssert(summary.outcome==='unavailable'&&summary.actualAttempts===0&&summary.cacheHits===0&&PROBE_ERRORS.includes(summary.errorCategory)&&!['officialSourceUrl','officialRowCount','officialSha256'].some(key=>Object.hasOwn(summary,key)));
 const outcome=cases.length===3&&cases.every(item=>item.status==='complete')?'complete':cases.some(item=>item.coverage>0)?'partial':'unavailable';probeAssert(summary.outcome===outcome);
 return {...summary,expectedDates:[...dates],cases};
}
function sourceValidateArtifact(body,state){
 probeKeys(body,['summary.json','provenance.json','byteHashes']);const p=body['provenance.json'];probeKeys(p,['requestId','marketDate','sourceMode','sourceGitCommit','actionsRunId','actionsRunAttempt','repository']);
 probeAssert(p.requestId===state.plan.requestId&&p.marketDate===state.plan.marketDate&&p.sourceMode==='institutional_probe'&&p.sourceGitCommit===state.plan.probeHeadSha&&p.actionsRunId===String(state.runId)&&p.actionsRunAttempt===String(state.runAttempt)&&p.repository==='pingpongtech-uskg/stock-web-pages');
 probeKeys(body.byteHashes,['summary','provenance']);probeAssert(Object.values(body.byteHashes).every(value=>/^[a-f0-9]{64}$/.test(value)));
 return {summary:sourceValidateSummary(body['summary.json'],state),byteHashes:{...body.byteHashes}};
}
async function sourceReadArtifact(files,readBuffer){
 const entries=Object.entries(files||{});probeAssert(entries.length===2&&entries.every(([,file])=>['summary.json','provenance.json'].includes(file.fileName))&&new Set(entries.map(([,file])=>file.fileName)).size===2);
 const body={};const hashes={};for(const [key,file] of entries){const bytes=await readBuffer(key);probeAssert(bytes.length>0&&bytes.length<=1000000);body[file.fileName]=JSON.parse(bytes.toString('utf8'));hashes[file.fileName.slice(0,-5)]=require('crypto').createHash('sha256').update(bytes).digest('hex');}
 return {...body,byteHashes:hashes};
}
if(typeof module!=='undefined')module.exports={sourceValidateArtifact,sourceReadArtifact};
