// Caller supplies bytes authenticated against an immutable GitHub publication commit.
const {validateExport,stockProperties}=require('./runtime.cjs');
function modernAuditEvidence(raw,expected){
 const payload=validateExport(raw,expected);
 if(!/^[a-f0-9]{40}$/.test(expected.sourceGitCommit||'')||payload.sourceGitCommit!==expected.sourceGitCommit)throw Error('audit_source_commit');
 const rankFields=['投信排名','成長排名','低位階排名'];
 const stocks=payload.selectedStocks.map(stock=>{
  const properties=stockProperties(stock,payload);
  const metrics=Object.fromEntries(Object.entries(properties).filter(([name,value])=>Object.hasOwn(value,'number')&&!rankFields.includes(name)).map(([name,value])=>[name,value.number]));
  return {code:stock.code,name:stock.name||stock.code,sector:stock.sector,strategies:stock.strategies,metrics,metricsJson:JSON.stringify(stock.metrics),provenanceJson:JSON.stringify(stock.provenance)};
 });
 return {marketDate:payload.marketDate,payloadHash:payload.payloadHash,revision:payload.revision,requestId:payload.requestId,actionsRunId:payload.actionsRunId,runId:payload.runId,sourceGitCommit:payload.sourceGitCommit,stocks};
}
module.exports={modernAuditEvidence};
