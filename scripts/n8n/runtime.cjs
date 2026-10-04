// Embedded in n8n Code nodes. No network calls or credential access.
const STRATEGIES = ['trust', 'growth', 'lowPosition'];
const METRICS = ['currentPrice','zScore','slope','currentPeg','currentPe','ttmEps','earningsGrowth','dividendYield','growthTotalReturnPe','growthFairPrice','growthBuyZonePrice','growthYears','growthValidYears','growthHealthPassCount','institutionNetShares10','participation10'];
function sha256(text) {
  const bytes = Buffer.from(text, 'utf8');
  const primes = []; const initial = []; const constants = [];
  for (let n = 2; primes.length < 64; n++) {
    if (primes.every(p => n % p)) {
      primes.push(n); constants.push((Math.cbrt(n) % 1 * 0x100000000) | 0);
      if (initial.length < 8) initial.push((Math.sqrt(n) % 1 * 0x100000000) | 0);
    }
  }
  const length = bytes.length; const padded = Buffer.alloc(Math.ceil((length + 9) / 64) * 64);
  bytes.copy(padded); padded[length] = 128; padded.writeUInt32BE(length * 8 >>> 0, padded.length - 4);
  const rotate = (x, n) => x >>> n | x << (32 - n);
  let hash = initial;
  for (let offset = 0; offset < padded.length; offset += 64) {
    const words = Array.from({length:64}, (_,i) => i < 16 ? padded.readUInt32BE(offset + 4*i) : 0);
    for (let i=16;i<64;i++) {
      const a=words[i-15], b=words[i-2];
      words[i]=(words[i-16]+(rotate(a,7)^rotate(a,18)^a>>>3)+words[i-7]+(rotate(b,17)^rotate(b,19)^b>>>10))|0;
    }
    let [a,b,c,d,e,f,g,h]=hash;
    for(let i=0;i<64;i++) {
      const t1=(h+(rotate(e,6)^rotate(e,11)^rotate(e,25))+(e&f^~e&g)+constants[i]+words[i])|0;
      const t2=((rotate(a,2)^rotate(a,13)^rotate(a,22))+(a&b^a&c^b&c))|0;
      [a,b,c,d,e,f,g,h]=[(t1+t2)|0,a,b,c,(d+t1)|0,e,f,g];
    }
    hash=hash.map((value,i)=>(value+[a,b,c,d,e,f,g,h][i])|0);
  }
  return hash.map(value=>(value>>>0).toString(16).padStart(8,'0')).join('');
}
function validateGrowthCoverage(funnel) {
  const fields=['growthInputComplete','growthValuationComplete','growthThresholdCandidates','growthHealthCandidates','growthCandidates'];
  const terminal=funnel?.growthTerminalOutcomes;
  const keys=['universe','missing','knownInvalid','extreme','belowThreshold','healthBlocked','selected'];
  if(funnel?.growthCoverageVersion!=='growth-coverage-v1'||funnel.version!=='funnel-v2-independent-trust-low-position'||!terminal||Object.keys(terminal).sort().join(',')!==[...keys].sort().join(',')||fields.some(key=>!Number.isInteger(funnel[key])||funnel[key]<0)||keys.some(key=>!Number.isInteger(terminal[key])||terminal[key]<0))throw Error('growth_coverage_schema');
  if(!Number.isInteger(funnel.universe)||funnel.universe<0||!Number.isInteger(funnel.instrumentExcluded)||funnel.instrumentExcluded<0||funnel.instrumentExcluded>funnel.universe||terminal.universe!==funnel.universe-funnel.instrumentExcluded)throw Error('growth_coverage_universe_source');
  if(keys.slice(1).reduce((sum,key)=>sum+terminal[key],0)!==terminal.universe||fields.some(key=>funnel[key]>terminal.universe)||funnel.growthValuationComplete>funnel.growthInputComplete)throw Error('growth_coverage_conservation');
  if(terminal.selected!==funnel.growthCandidates||funnel.growthCandidates!==funnel.growthHealthCandidates||terminal.healthBlocked+terminal.selected!==funnel.growthThresholdCandidates||terminal.belowThreshold+funnel.growthThresholdCandidates!==funnel.growthValuationComplete)throw Error('growth_coverage_funnel');
  const state=!terminal.universe||terminal.missing===terminal.universe?'not_evaluable':terminal.missing?'partial':'evaluated';
  if(funnel.growthEvaluationState!==state||!Array.isArray(funnel.growthMissingReasons)||funnel.growthMissingReasons.some(item=>typeof item?.reason!=='string'||!item.reason||!Number.isInteger(item.count)||item.count<1||item.count>terminal.universe)||new Set(funnel.growthMissingReasons.map(item=>item.reason)).size!==funnel.growthMissingReasons.length)throw Error('growth_coverage_evaluation');
}
function validateChipReference(chip) {
  const statuses=['pass','fail','unknown'];
  const refs=value=>Array.isArray(value)&&value.every(ref=>typeof ref==='string'&&ref.length>0);
  const number=value=>typeof value==='number'&&Number.isFinite(value);
  const sourceDate=value=>typeof value==='string'&&Number(value.slice(0,4))>0&&(/^\d{4}-(0[1-9]|1[0-2])$/.test(value)||(/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value));
  if(!chip||chip.schemaVersion!=='chip-reference-v1'||chip.formulaVersion!=='chip-reference-v1'||chip.displayOnly!==true||!statuses.includes(chip.status)||!['current','stale','unavailable','unknown'].includes(chip.dataFreshness)||!refs(chip.sourceRefs))throw Error('chip_reference_schema');
  for(const key of ['largeHolderTrend','directorSupervisor12m','shareholderCountTrend']) {
    const value=chip[key];
    if(!value||!statuses.includes(value.status)||typeof value.value!=='string'||!value.value||typeof value.period!=='string'||!value.period||!refs(value.sourceRefs))throw Error('chip_reference_indicator');
    if(value.sourceDates!==undefined&&(!Array.isArray(value.sourceDates)||!value.sourceDates.every(sourceDate)))throw Error('chip_reference_source_dates');
    if(value.retrievedAt!==undefined&&value.retrievedAt!==null&&(typeof value.retrievedAt!=='string'||!Number.isFinite(Date.parse(value.retrievedAt))))throw Error('chip_reference_retrieved_at');
    if(value.historicalBackfill!==undefined&&typeof value.historicalBackfill!=='boolean')throw Error('chip_reference_backfill');
    if(value.rawValues!==undefined&&(key==='directorSupervisor12m'?(!value.rawValues||!number(value.rawValues.latest)||!number(value.rawValues.prior12m)):(!Array.isArray(value.rawValues)||value.rawValues.length!==3||!value.rawValues.every(number))))throw Error('chip_reference_raw_values');
  }
}
function validateExport(raw, expected) {
  if (typeof raw !== 'string' || Buffer.byteLength(raw)>3000000) throw Error('export_size');
  const suffix = /,"payloadHash":"([a-f0-9]{64})"}$/;
  const match = raw.match(suffix);
  if (!match || sha256(raw.replace(suffix,'}')) !== match[1]) throw Error('payload_hash_mismatch');
  const value=JSON.parse(raw);
  if (value.schemaVersion!=='screening-export-v1' || value.legacy!==false || !/^[a-f0-9]{12}$/.test(value.revision)) throw Error('export_schema');
  for(const field of ['marketDate','requestId','actionsRunId']) if(value[field]!==expected[field]) throw Error('export_lineage:'+field);
  if(!/^[a-f0-9]{40}$/.test(value.sourceGitCommit) || !value.runId || !value.generatedAt || !value.formulaVersions || !value.coverage || !value.funnel) throw Error('export_lineage');
  if(!['current','degraded'].includes(value.freshness) || value.coverage.universeStale) throw Error('stale_export');
  validateGrowthCoverage(value.funnel);
  if(!Array.isArray(value.selectedStocks) || value.selectedStocks.length>3000 || Object.keys(value.strategies||{}).sort().join(',')!==[...STRATEGIES].sort().join(',')) throw Error('export_schema');
  const codes=value.selectedStocks.map(stock=>stock.code);
  if(codes.some(code=>typeof code!=='string'||!/^\d{4,6}$/.test(code)) || new Set(codes).size!==codes.length) throw Error('selected_stock_duplicates');
  const union=new Set();
  for(const strategy of STRATEGIES) {
    const rows=value.strategies[strategy]; if(!Array.isArray(rows)) throw Error('strategy_rows');
    if(strategy==='growth'&&rows.length!==value.funnel.growthCandidates)throw Error('growth_coverage_strategy_count');
    const members=rows.map(row=>`${row.code}:${row.rank}`);
    if(new Set(members).size!==members.length||new Set(rows.map(row=>row.code)).size!==rows.length||new Set(rows.map(row=>row.rank)).size!==rows.length||rows.some(row=>!Number.isInteger(row.rank)||row.rank<1)) throw Error('strategy_duplicates');
    rows.forEach(row=>union.add(row.code));
    const actual=value.selectedStocks.flatMap(stock=>(stock.strategies||[]).filter(entry=>entry.strategy===strategy).map(entry=>`${stock.code}:${entry.rank}`));
    if(actual.sort().join(',')!==members.sort().join(',')) throw Error('strategy_union_mismatch');
  }
  if([...union].sort().join(',')!==[...codes].sort().join(',')) throw Error('selected_union_mismatch');
  for(const stock of value.selectedStocks) {
    if(stock.chipReference!==undefined)validateChipReference(stock.chipReference);
    if(typeof stock.name!=='string'||typeof stock.sector!=='string'||!stock.metrics||!stock.provenance||stock.provenance.marketDate!==value.marketDate) throw Error('stock_schema');
    if(stock.strategies.some(entry=>!STRATEGIES.includes(entry.strategy)||typeof entry.status!=='string'||typeof entry.reason!=='string')) throw Error('stock_strategy_schema');
    if(METRICS.some(name=>stock.metrics[name]!==undefined&&stock.metrics[name]!==null&&(typeof stock.metrics[name]!=='number'||!Number.isFinite(stock.metrics[name])))) throw Error('stock_metric_schema');
    if(stock.metrics.growthMethod!==undefined&&stock.metrics.growthMethod!==null&&typeof stock.metrics.growthMethod!=='string') throw Error('stock_metric_schema');
  }
  return value;
}
function richText(content) {
  const text=String(content); const parts=[];
  for(let i=0;i<text.length;i+=1900) parts.push({type:'text',text:{content:text.slice(i,i+1900)}});
  if(parts.length>100) throw Error('notion_text_too_large');
  return parts;
}
const CHIP_NUMBERS=['大股東持股比重最新','董監持股比重最新','董監持股比重去年同月','股東人數最新'];
const CHIP_TEXT=['籌碼狀態','籌碼新鮮度','籌碼觀察期間','籌碼觀察日期','籌碼來源','籌碼參考'];
function chipProperties(chip) {
  const number=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
  const large=chip?.largeHolderTrend, director=chip?.directorSupervisor12m, shareholders=chip?.shareholderCountTrend;
  const latest=indicator=>Array.isArray(indicator?.rawValues)?number(indicator.rawValues.at(-1)):null;
  const checks={largeHolderTrend:large,directorSupervisor12m:director,shareholderCountTrend:shareholders};
  return {'大股東持股比重最新':{number:latest(large)},'董監持股比重最新':{number:number(director?.rawValues?.latest)},'董監持股比重去年同月':{number:number(director?.rawValues?.prior12m)},'股東人數最新':{number:latest(shareholders)},'籌碼狀態':{rich_text:richText(JSON.stringify({overall:chip?.status||'unknown',...Object.fromEntries(Object.entries(checks).map(([key,value])=>[key,value?.status||'unknown']))}))},'籌碼新鮮度':{rich_text:richText(chip?.dataFreshness||'unavailable')},'籌碼觀察期間':{rich_text:richText(JSON.stringify(Object.fromEntries(Object.entries(checks).map(([key,value])=>[key,value?.period||'—']))))},'籌碼觀察日期':{rich_text:richText(JSON.stringify(Object.fromEntries(Object.entries(checks).map(([key,value])=>[key,value?.sourceDates||[]]))))},'籌碼來源':{rich_text:richText(JSON.stringify(chip?.sourceRefs||[]))},'籌碼參考':{rich_text:richText(JSON.stringify(chip||{status:'unknown',displayOnly:true,dataFreshness:'unavailable'}))}};
}
function stockSchema() {
  return {'名稱':{title:{}},'股票代號':{rich_text:{}},'產業':{rich_text:{}},'策略':{multi_select:{options:STRATEGIES.map(name=>({name}))}},'投信排名':{number:{}},'成長排名':{number:{}},'低位階排名':{number:{}},'指標':{rich_text:{}},'來源':{rich_text:{}},'策略狀態':{rich_text:{}},'Revision':{rich_text:{}},'Payload Hash':{rich_text:{}},'Row Key':{rich_text:{}},...Object.fromEntries([...METRICS,...CHIP_NUMBERS].map(name=>[name,{number:{}}])),...Object.fromEntries(CHIP_TEXT.map(name=>[name,{rich_text:{}}]))};
}
function stockProperties(stock, payload) {
  const rank = name => stock.strategies.find(entry=>entry.strategy===name)?.rank??null;
  return {'名稱':{title:richText(stock.name||stock.code)},'股票代號':{rich_text:richText(stock.code)},'產業':{rich_text:richText(stock.sector)},'策略':{multi_select:stock.strategies.map(entry=>({name:entry.strategy}))},'投信排名':{number:rank('trust')},'成長排名':{number:rank('growth')},'低位階排名':{number:rank('lowPosition')},'指標':{rich_text:richText(JSON.stringify(stock.metrics))},'來源':{rich_text:richText(JSON.stringify(stock.provenance))},'策略狀態':{rich_text:richText(JSON.stringify(stock.strategies))},'Revision':{rich_text:richText(payload.revision)},'Payload Hash':{rich_text:richText(payload.payloadHash)},'Row Key':{rich_text:richText(`${payload.payloadHash}:${stock.code}`)},...Object.fromEntries(METRICS.map(name=>[name,{number:stock.metrics[name]??null}])),...chipProperties(stock.chipReference)};
}
function retrySeconds(value,now=Date.now()) {
  if(value!==undefined&&String(value).trim()!==''&&Number.isFinite(Number(value))) return Math.max(0.5,Number(value));
  const timestamp=Date.parse(value); return Number.isFinite(timestamp)?Math.max(0.5,(timestamp-now)/1000):2;
}
function claimState(existing, owner) {
  if(existing?.owner&&existing.owner!==owner&&!existing.released) throw Error('writer_busy');
  return {...(existing||{}),owner,released:false};
}
if(typeof module!=='undefined') module.exports={validateExport,validateGrowthCoverage,stockProperties,stockSchema,richText,retrySeconds,claimState,sha256};
