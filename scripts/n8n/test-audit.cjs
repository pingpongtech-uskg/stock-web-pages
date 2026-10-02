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
