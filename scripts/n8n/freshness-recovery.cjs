// Decide whether a verified degraded release needs a new bounded acquisition.
// GitHub CAS and clearing per-run state remain the caller's responsibility.
const FRESHNESS_REFRESH_LIMIT=6;
const FRESHNESS_REFRESH_DELAY_MS=30*60000;
const GAP_KEYS=['price','regression','institution'];
function record(value){return value!==null&&typeof value==='object'&&!Array.isArray(value);}
function marketDateValid(value){
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;
 const parsed=Date.parse(value+'T00:00:00Z');
 return Number.isFinite(parsed)&&new Date(parsed).toISOString().slice(0,10)===value;
}
function publicationTime(value){
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,9})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value)||!marketDateValid(value.slice(0,10)))return NaN;
 return Date.parse(value);
}
function actionableGaps(gaps){
 if(!record(gaps)||!GAP_KEYS.every(key=>Array.isArray(gaps[key])))return false;
 if(!GAP_KEYS.every(key=>gaps[key].every(code=>typeof code==='string'&&/^\d{4,6}$/.test(code))))return false;
 return GAP_KEYS.some(key=>gaps[key].length>0);
}
function publicationFreshnessEvidence(payload){
 const publication=record(payload)?payload:{};
 const warnings=Array.isArray(publication.dataQuality?.warnings)?publication.dataQuality.warnings:[];
 const warningKeys={price_date:'price',regression_date:'regression',institution_date:'institution',institution_window_incomplete:'institution'};
 const gaps={price:new Set(),regression:new Set(),institution:new Set()};
 for(const warning of warnings){
  if(!record(warning)||!Object.hasOwn(warningKeys,warning.code)||typeof warning.stockCode!=='string'||!/^\d{4,6}$/.test(warning.stockCode))continue;
  gaps[warningKeys[warning.code]].add(warning.stockCode);
 }
 return {publicationFreshness:['current','degraded'].includes(publication.freshness)?publication.freshness:'unknown',
  publicationGeneratedAt:typeof publication.generatedAt==='string'?publication.generatedAt:null,
  publicationFreshnessGaps:Object.fromEntries(GAP_KEYS.map(key=>[key,[...gaps[key]].sort()]))};
}
function planFreshnessRecovery(existing,incoming,now){
 if(!record(existing)||!record(incoming)||typeof now!=='number'||!Number.isFinite(now))return null;
 if(incoming.runKind!=='scheduled'||incoming.mode!=='screen'||incoming.automaticRequestId!==true)return null;
 if(!marketDateValid(existing.marketDate)||incoming.marketDate!==existing.marketDate)return null;
 if(existing.released!==true||existing.screeningStatus!=='complete'||existing.publicationStatus!=='verified'||existing.deployStatus!=='verified')return null;
 if(existing.publicationFreshness!=='degraded'||!actionableGaps(existing.publicationFreshnessGaps))return null;
 const requestValid=value=>typeof value==='string'&&/^[a-zA-Z0-9_.:-]{1,160}$/.test(value);
 if(!requestValid(existing.requestId)||(incoming.requestId!==undefined&&!requestValid(incoming.requestId)))return null;
 const count=existing.freshnessRefreshCount===undefined?0:existing.freshnessRefreshCount;
 if(!Number.isSafeInteger(count)||count<0||count>=FRESHNESS_REFRESH_LIMIT)return null;
 const generatedAt=publicationTime(existing.publicationGeneratedAt);
 if(!Number.isFinite(generatedAt)||now-generatedAt<FRESHNESS_REFRESH_DELAY_MS)return null;
 const nextCount=count+1;
 return {mode:'revision',requestId:`stockscreener:${existing.marketDate.replaceAll('-','')}:refresh${nextCount}`,
  freshnessRefreshCount:nextCount,previousPublishedRequestId:existing.requestId};
}
module.exports={planFreshnessRecovery,publicationFreshnessEvidence};
