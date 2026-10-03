// Read-only verification; only the workflow's outcome ledger is appended.
function auditText(property){return property?.rich_text?.map(part=>part.plain_text||part.text?.content||'').join('')||'';}
function auditRequest(state,url,body,method='POST'){return {state,op:{method,url,body},route:'read',delaySeconds:0.5};}
function auditDaily(state){return auditRequest({...state,stage:'daily'},'https://api.notion.com/v1/data_sources/3ed6fb57-ff38-803d-815a-000b148c6b6e/query',{filter:{property:'名稱',title:{equals:state.dates[state.index].replaceAll('-','')}},page_size:100});}
function auditNext(state,result){const next={...state,index:state.index+1,results:[...state.results,result],rows:[]};return next.index<next.dates.length?auditDaily(next):{state:{...next,stage:'done'},op:null,route:'done',delaySeconds:0.5};}
function auditStart(dates,owner,expectedStocks){if(!Array.isArray(dates)||!dates.length||dates.some(date=>!/^\d{4}-\d{2}-\d{2}$/.test(date)))throw Error('audit_dates');return auditDaily({dates,index:0,owner,results:[],rows:[],...(expectedStocks?{expectedStocks}:{})});}
function auditBlocks(state,cursor){return auditRequest({...state,stage:'blocks'},`https://api.notion.com/v1/blocks/${state.current.pageId}/children?page_size=100${cursor?'&start_cursor='+encodeURIComponent(cursor):''}`,null,'GET');}
function auditValues(rows,expectedStocks){
 const rankNames={trust:'投信排名',growth:'成長排名',lowPosition:'低位階排名'};let checkedNumbers=0,nullNumbers=0,zeroNumbers=0;
 const verified=rows.length===expectedStocks.length&&rows.every(row=>{
  const expected=expectedStocks.find(stock=>stock.code===auditText(row.properties['股票代號']));if(!expected)return false;
  const tags=row.properties['策略']?.multi_select?.map(item=>item.name).sort().join(',');if(tags!==expected.strategies.map(item=>item.strategy).sort().join(','))return false;
  if(Object.entries(rankNames).some(([name,field])=>row.properties[field]?.number!==(expected.strategies.find(item=>item.strategy===name)?.rank??null)))return false;
  return Object.entries(expected.metrics).every(([name,value])=>{checkedNumbers++;if(value===null)nullNumbers++;if(value===0)zeroNumbers++;return row.properties[name]?.number===value;});
 });return {stockValuesVerified:verified,checkedNumbers,nullNumbers,zeroNumbers};
}
function auditRows(state,cursor){return auditRequest({...state,stage:'rows'},`https://api.notion.com/v1/data_sources/${state.current.dataSourceId}/query`,{filter:{property:'Payload Hash',rich_text:{equals:state.current.payloadHash}},page_size:100,...(cursor?{start_cursor:cursor}:{})});}
function auditAdvance(state,response){
 const date=state.dates[state.index];let body=response.body??response.data;
 if(response.statusCode<200||response.statusCode>=300)return auditNext(state,{marketDate:date,status:'failed',error:'notion_http_'+response.statusCode});
 if(typeof body==='string')body=JSON.parse(body);
 if(!Array.isArray(body.results))return auditNext(state,{marketDate:date,status:'failed',error:'response_schema'});
 if(state.stage==='daily'){
  if(body.results.length!==1||body.has_more)return auditNext(state,{marketDate:date,status:body.results.length?'failed':'missing',error:'daily_page_count',pageCount:body.results.length});
  const page=body.results[0];const p=page.properties;const current={marketDate:date,pageId:page.id,dataSourceId:auditText(p['Child Data Source ID']),databaseId:auditText(p['Child Database ID']),payloadHash:auditText(p['Payload Hash']),revision:auditText(p['Active Revision']),notionStatus:auditText(p['Notion Status']),expectedCount:p['Expected Count']?.number,archivedCount:p['Archived Count']?.number};
  if(!/^[a-f0-9-]{36}$/.test(current.dataSourceId)||!/^[a-f0-9]{64}$/.test(current.payloadHash)||!/^[a-f0-9]{12}$/.test(current.revision)||!Number.isInteger(current.expectedCount)||current.expectedCount<0)return auditNext(state,{...current,status:'failed',error:'root_archive_metadata'});
  return state.expectedStocks?auditBlocks({...state,current,rows:[],childDatabases:[]}):auditRows({...state,current,rows:[]});
 }
 if(state.stage==='blocks'){
  const childDatabases=[...state.childDatabases,...body.results.filter(block=>block.type==='child_database'&&block.child_database.title===date.replaceAll('-',''))];
  if(body.has_more)return auditBlocks({...state,childDatabases},body.next_cursor);
  if(childDatabases.length!==1||childDatabases[0].id!==state.current.databaseId)return auditNext(state,{...state.current,status:'failed',error:'child_database_count',childDatabaseCount:childDatabases.length});
  return auditRows({...state,current:{...state.current,childDatabaseCount:1},childDatabases:[]});
 }
 const rows=[...state.rows,...body.results];if(rows.length>3000)return auditNext(state,{marketDate:date,status:'failed',error:'row_limit'});
 if(body.has_more)return auditRows({...state,rows},body.next_cursor);
 const keys=rows.map(row=>auditText(row.properties['Row Key']));const codes=rows.map(row=>auditText(row.properties['股票代號']));
 const valid=state.current.notionStatus==='complete'&&state.current.expectedCount===rows.length&&state.current.archivedCount===rows.length&&new Set(keys).size===rows.length&&new Set(codes).size===rows.length&&rows.every((row,index)=>/^\d{4,6}$/.test(codes[index])&&keys[index]===state.current.payloadHash+':'+codes[index]&&auditText(row.properties['Revision'])===state.current.revision);
 const values=state.expectedStocks?auditValues(rows,state.expectedStocks[date]||[]):{};
 return auditNext(state,{...state.current,...values,status:valid&&values.stockValuesVerified!==false?'verified':'failed',rowCount:rows.length,uniqueRowKeys:new Set(keys).size,codes});
}
if(typeof module!=='undefined')module.exports={auditStart,auditAdvance};
