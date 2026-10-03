const test=require('node:test');const assert=require('node:assert/strict');let audit={};try{audit=require('./audit.cjs');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
const date='2026-09-08';const text=value=>({rich_text:[{text:{content:value}}]});
const root={id:'page',properties:{'Payload Hash':text('a'.repeat(64)),'Active Revision':text('b'.repeat(12)),'Child Data Source ID':text('11111111-1111-1111-1111-111111111111'),'Child Database ID':text('22222222-2222-2222-2222-222222222222'),'Notion Status':text('complete'),'Expected Count':{number:1},'Archived Count':{number:1}}};
const stock={id:'stock',properties:{'Row Key':text('a'.repeat(64)+':0050'),'股票代號':text('0050'),'Revision':text('b'.repeat(12))}};
test('audit reads actual paginated counts and unique active row keys independently',()=>{
 assert.equal(typeof audit.auditStart,'function');let out=audit.auditStart([date],'owner');assert.equal(out.op.method,'POST');
 out=audit.auditAdvance(out.state,{statusCode:200,data:JSON.stringify({results:[root],has_more:false})});assert.ok(out.op.url.includes('/data_sources/11111111-1111-1111-1111-111111111111/query'));
 out=audit.auditAdvance(out.state,{statusCode:200,body:{results:[stock],has_more:true,next_cursor:'next'}});assert.equal(out.op.body.start_cursor,'next');
 out=audit.auditAdvance(out.state,{statusCode:200,body:{results:[],has_more:false}});assert.equal(out.route,'done');assert.equal(out.state.results[0].status,'verified');assert.equal(out.state.results[0].rowCount,1);
});
test('audit catches missing daily metadata and duplicate actual active stock rows',()=>{
 let out=audit.auditStart([date],'owner');out=audit.auditAdvance(out.state,{statusCode:200,body:{results:[],has_more:false}});assert.equal(out.state.results[0].status,'missing');
 out=audit.auditStart([date],'owner');out=audit.auditAdvance(out.state,{statusCode:200,body:{results:[root],has_more:false}});out=audit.auditAdvance(out.state,{statusCode:200,body:{results:[stock,stock],has_more:false}});assert.equal(out.state.results[0].status,'failed');assert.equal(out.state.results[0].uniqueRowKeys,1);
});
test('audit handles malformed metadata, unavailable API and multiple requested dates explicitly',()=>{
 assert.throws(()=>audit.auditStart([], 'owner'),/audit_dates/);assert.throws(()=>audit.auditStart(['bad'], 'owner'),/audit_dates/);
 let out=audit.auditStart([date,'2026-09-11'],'owner');out=audit.auditAdvance(out.state,{statusCode:503,body:{}});assert.equal(out.state.results[0].error,'notion_http_503');assert.equal(out.state.index,1);
 out=audit.auditAdvance(out.state,{statusCode:200,body:{unexpected:true}});assert.equal(out.state.results[1].error,'response_schema');
 out=audit.auditStart([date],'owner');out=audit.auditAdvance(out.state,{statusCode:200,body:{results:[root,root],has_more:false}});assert.equal(out.state.results[0].status,'failed');
 out=audit.auditStart([date],'owner');out=audit.auditAdvance(out.state,{statusCode:200,body:{results:[{...root,properties:{}}],has_more:false}});assert.equal(out.state.results[0].error,'root_archive_metadata');
});
test('independent audit checks inline database uniqueness and exact numeric null zero tags and ranks',()=>{
 const expected={[date]:[{code:'0050',strategies:[{strategy:'trust',rank:1}],metrics:{currentPrice:0,ttmEps:null}}]};
 let out=audit.auditStart([date],'owner',expected);out=audit.auditAdvance(out.state,{statusCode:200,body:{results:[root],has_more:false}});
 assert.equal(out.state.stage,'blocks');assert.equal(out.op.method,'GET');
 out=audit.auditAdvance(out.state,{statusCode:200,body:{results:[{id:'22222222-2222-2222-2222-222222222222',type:'child_database',child_database:{title:'20260908'}}],has_more:false}});
 const actual={...stock,properties:{...stock.properties,'策略':{multi_select:[{name:'trust'}]},'投信排名':{number:1},'成長排名':{number:null},'低位階排名':{number:null},currentPrice:{number:0},ttmEps:{number:null}}};
 const good=audit.auditAdvance(out.state,{statusCode:200,body:{results:[actual],has_more:false}}).state.results[0];assert.equal(good.status,'verified');assert.equal(good.childDatabaseCount,1);assert.equal(good.stockValuesVerified,true);assert.equal(good.nullNumbers,1);assert.equal(good.zeroNumbers,1);
 const wrong=audit.auditAdvance(out.state,{statusCode:200,body:{results:[{...actual,properties:{...actual.properties,ttmEps:{number:0}}}],has_more:false}}).state.results[0];assert.equal(wrong.status,'failed');assert.equal(wrong.stockValuesVerified,false);
 const duplicate=audit.auditAdvance({...out.state,stage:'blocks',childDatabases:[]},{statusCode:200,body:{results:[{id:'db',type:'child_database',child_database:{title:'20260908'}},{id:'db2',type:'child_database',child_database:{title:'20260908'}}],has_more:false}});assert.equal(duplicate.state.results[0].error,'child_database_count');
});
