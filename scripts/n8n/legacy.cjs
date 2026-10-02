// Explicit projection of immutable retained history; original lineage stays unknown.
const {sha256}=require('./runtime.cjs');
function validateLegacyArchive(raw,expected) {
  if(typeof raw!=='string'||Buffer.byteLength(raw)>3000000||sha256(raw)!==expected.sha256)throw Error('legacy_hash_mismatch');
  const record=JSON.parse(raw);const names=['trust','growth','lowPosition'];
  if((record.schemaVersion!==undefined&&record.schemaVersion!=='screening-history-record-v1')||record.legacy!==true||!/^[a-f0-9]{12}$/.test(record.revision)||!/^[a-f0-9]{40}$/.test(expected.archiveCommit))throw Error('legacy_schema');
  for(const name of ['marketDate','revision','runId'])if(record[name]!==expected[name])throw Error('legacy_lineage:'+name);
  if(Object.keys(record.strategies||{}).sort().join(',')!==[...names].sort().join(','))throw Error('legacy_strategy_schema');
  const metricNames=['currentPrice','zScore','slope','currentPeg','currentPe','ttmEps','earningsGrowth','dividendYield','growthTotalReturnPe','growthFairPrice','growthBuyZonePrice','growthYears','growthValidYears','growthHealthPassCount','institutionNetShares10','participation10'];
  let selected={};const strategies={};
  for(const strategy of names) {
    const rows=record.strategies[strategy];if(!Array.isArray(rows)||rows.length>3000)throw Error('legacy_strategy_schema');
    if(new Set(rows.map(row=>row.code)).size!==rows.length||new Set(rows.map(row=>row.rank)).size!==rows.length)throw Error('legacy_strategy_duplicates');
    strategies[strategy]=rows.map(row=>({code:row.code,rank:row.rank}));
    for(const row of rows) {
      if(typeof row.code!=='string'||!/^\d{4,6}$/.test(row.code)||!Number.isInteger(row.rank)||row.rank<1||typeof row.name!=='string')throw Error('legacy_stock_schema');
      if(metricNames.some(name=>row[name]!==undefined&&row[name]!==null&&(typeof row[name]!=='number'||!Number.isFinite(row[name]))))throw Error('legacy_metric_schema');
      const previous=selected[row.code];
      const metrics=Object.fromEntries(metricNames.map(name=>[name,previous?.metrics[name]??row[name]??null]));
      const provenance={marketDate:record.marketDate,sourceRefs:record.sourceRefs||[],inputOrigins:'legacy_archive',dataStatus:'legacy_archive',financialCutoff:'unknown',valuationEvidenceLevel:'legacy_archive',archiveSourceGitCommit:expected.archiveCommit,archiveRevisionSha256:expected.sha256,legacyReason:record.legacyReason||'Original Actions and source commit lineage unavailable.',strategyRows:{...(previous?.provenance.strategyRows||{}),[strategy]:row}};
      selected={...selected,[row.code]:{code:row.code,name:row.name,sector:typeof row.sector==='string'?row.sector:'',metrics,strategies:[...(previous?.strategies||[]),{strategy,rank:row.rank,status:String(row.status||'unknown'),reason:String(row.reason||'')}],provenance}};
    }
  }
  return {schemaVersion:'legacy-archive-projection-v1',marketDate:record.marketDate,generatedAt:record.generatedAt,runId:record.runId,requestId:`legacy:${record.marketDate}:${record.revision}`,sourceGitCommit:'',actionsRunId:'',revision:record.revision,formulaVersions:record.formulaVersions||{},legacy:true,freshness:'legacy_archive',coverage:{legacyArchive:true,originalFreshness:record.freshness||'unknown'},funnel:record.funnel||{},strategies,selectedStocks:Object.values(selected).sort((a,b)=>a.code.localeCompare(b.code)),payloadHash:expected.sha256};
}
if(typeof module!=='undefined')module.exports={validateLegacyArchive};
