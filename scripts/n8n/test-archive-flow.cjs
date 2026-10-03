const {growthFixture}=require('./growth-fixture.cjs');
const test=require('node:test');const assert=require('node:assert/strict');const crypto=require('node:crypto');
const {start,advance}=require('./engine.cjs');const {stockProperties,stockSchema}=require('./runtime.cjs');
// Unit integration fixtures stay local. They are never sent to the real service.
const {fixture:cacheFixture}=require('./cache-fixture.cjs');const marketCache=require('./market-cache.cjs');
const now=Date.parse('2026-10-02T10:00:00Z');
function fixture(zero=false) {
  const strategies=zero?{trust:[],growth:[],lowPosition:[]}:{trust:[{code:'0050',rank:1}],growth:[],lowPosition:[]};
  const selectedStocks=zero?[]:[{code:'0050',name:'Local fixture',sector:'test',metrics:{currentPrice:100,growthMethod:'eps_growth'},strategies:[{strategy:'trust',rank:1,status:'ok',reason:''}],provenance:{marketDate:'2026-10-02',financialCutoff:'2026-Q2'}}];
  const body={schemaVersion:'screening-export-v1',marketDate:'2026-10-02',generatedAt:'2026-10-02T10:00:00Z',requestId:'local-test',actionsRunId:'123',runId:'local-run',sourceGitCommit:'a'.repeat(40),revision:'b'.repeat(12),formulaVersions:{ranking:'v1'},legacy:false,freshness:'current',coverage:{},funnel:growthFixture(),strategies,selectedStocks};
  const preimage=JSON.stringify(body);const payloadHash=crypto.createHash('sha256').update(preimage).digest('hex');
  const raw=preimage.slice(0,-1)+',"payloadHash":"'+payloadHash+'"}';
  return {raw,payload:{...body,payloadHash},publication:{requestId:body.requestId,marketDate:body.marketDate,runId:body.runId,actionsRunId:body.actionsRunId,sourceGitCommit:body.sourceGitCommit,publishedGitCommit:'c'.repeat(40),payloadHash}};
}
function world(options={}) {
  const f=fixture(options.zero);const cf=cacheFixture(),source={requestId:f.payload.requestId,actionsRunId:f.payload.actionsRunId,sourceGitCommit:f.payload.sourceGitCommit};
  const latest=Buffer.from(JSON.stringify({marketDate:f.payload.marketDate,runId:f.payload.runId,stocks:[{code:'1240'},{code:'2330'}]})),latestHash=crypto.createHash('sha256').update(latest).digest('hex');
  const groups=cf.input.groups.map(g=>g.kind==='published_stock_inputs'?{...g,sourceSha256:latestHash}:g),expected={...cf.expected,source,groups:groups.map(({body,...g})=>g)},bundle=marketCache.buildMarketCache({...cf.input,source,groups});
  const checked=marketCache.verifyMarketCache(bundle.manifest,bundle.files,{...expected,manifestHash:bundle.manifest.manifestHash});
  const proof={schemaVersion:'market-cache-producer-proof-v1',semanticValidation:'bounded-python-v1',marketDate:f.payload.marketDate,previousTradingDate:cf.input.previousTradingDate,source,...checked};
  const cacheFiles={'manifest.json':Buffer.from(JSON.stringify(bundle.manifest)),'proof.json':Buffer.from(JSON.stringify(proof)),'expected.json':Buffer.from(JSON.stringify(expected)),...bundle.files};let cacheBlocks=[],uploadCounter=0;
  let rows=[],dailyPage=null,child=null,persisted=options.existing||null,schema={'名稱':{type:'title'}},summaries=[];
  let writes=0,ambiguous=!!options.ambiguous,liveAttempts=0,runPolls=0;
  const requests=[];
  function respond(output){
    requests.push(output.op);const {state,op}=output;const stage=state.stage;
    const ok=(body,statusCode=200,headers={})=>({body,statusCode,headers});
    switch(stage){
      case 'restoreState':return {statusCode:404,body:{}};
      case 'calendar':return ok([{Name:'國曆新年開始交易日',Date:'1150102'},{Name:'國慶日',Date:'1151009'}]);
      case 'branch':return options.createBranch&&!state.branchCreated?ok({},404):ok({object:{sha:'a'.repeat(40)}});
      case 'mainRef':return ok({object:{sha:'a'.repeat(40)}});
      case 'createBranch':return ok({},201);
      case 'state':return persisted?ok({sha:'state-sha',content:Buffer.from(JSON.stringify(persisted)).toString('base64')}):ok({},404);
      case 'checkpoint':persisted=JSON.parse(Buffer.from(op.body.content,'base64').toString('utf8'));writes++;return ok({content:{sha:'state-'+writes}},201);
      case 'findRun':return ok({workflow_runs:options.dispatch&&!state.dispatchIntent?[]:[{id:123,head_sha:'a'.repeat(40),display_title:'Daily screening | local-test | 2026-10-02'}]});
      case 'dispatch':return ok({},204);
      case 'pollRun':runPolls++;return ok({id:123,head_sha:'a'.repeat(40),display_title:'Daily screening | local-test | 2026-10-02',status:options.pendingOnce&&runPolls===1?'in_progress':'completed',conclusion:options.failure?'failure':'success'});
      case 'artifactList':return ok({artifacts:[{id:456,name:'screening-export',expired:false,workflow_run:{id:123,head_sha:'a'.repeat(40)}}]});
      case 'artifactRedirect':return ok('',302,{location:'https://production.blob.core.windows.net/artifacts/file.zip?signature=local-only'});
      case 'artifactZip':return ok({rawExport:f.raw,publication:f.publication});
      case 'publicationExport':return ok({encoding:'base64',size:Buffer.byteLength(f.raw),content:Buffer.from(f.raw).toString('base64')});
      case 'publicationMain':return ok({status:'ahead',base_commit:{sha:f.publication.publishedGitCommit}});
      case 'liveProbe':
      case 'liveVerify':liveAttempts++;return options.deployDelayed&&liveAttempts<3?ok('{}'):ok(f.raw);
      case 'rootSchema':return ok({properties:schema});
      case 'rootSchemaUpdate':schema={...schema,...Object.fromEntries(Object.entries(op.body.properties).map(([name,value])=>[name,{...value,type:Object.keys(value)[0]}]))};return ok({properties:schema});
      case 'findDaily':return ok({results:dailyPage?[dailyPage]:[],has_more:false});
      case 'createDaily':dailyPage={id:'33333333-3333-4333-8333-333333333333',properties:op.body.properties};return ok(dailyPage,201);
      case 'findDatabase':return ok({results:child?[{id:child.id,type:'child_database',child_database:{title:'20261002'}}]:[],has_more:false});
      case 'createDatabase':child={id:'child-database',data_sources:[{id:'child-source'}]};return ok(child,201);
      case 'databaseMetadata':return ok(child);
      case 'queryRows':
      case 'verifyRows':return ok({results:rows,has_more:false});
      case 'createStock':{
        const row={id:'stock-'+(rows.length+1),created_time:'2026-10-02T10:00:00Z',properties:op.body.properties};rows=[...rows,row];
        if(ambiguous){ambiguous=false;return ok({},503);}return ok(row,201);
      }
      case 'archiveDuplicate':rows=rows.filter(row=>!op.url.endsWith(row.id));return ok({archived:true});
      case 'cacheRun':return ok({id:123,head_sha:f.payload.sourceGitCommit,workflow_id:789,path:'.github/workflows/daily.yml',head_branch:'main',event:'workflow_dispatch',display_title:'Daily screening | local-test | 2026-10-02',status:'completed',conclusion:'success'});
      case 'cacheFingerprint':{const bytes=Buffer.from(JSON.stringify({schemaVersion:'publication-fingerprint-v1',marketDate:f.payload.marketDate,runId:f.payload.runId,contentHash:latestHash}));return ok({encoding:'base64',size:bytes.length,content:bytes.toString('base64')});}
      case 'cacheLatest':return ok({encoding:'base64',size:latest.length,content:latest.toString('base64')});
      case 'cacheArtifacts':return ok({artifacts:[{id:777,name:'market-cache',expired:false,size_in_bytes:1000,digest:'sha256:'+'d'.repeat(64),workflow_run:{id:123,head_sha:f.payload.sourceGitCommit}}]});
      case 'cacheRedirect':return ok('',302,{location:'https://production.blob.core.windows.net/artifacts/cache.zip?signature=local-only'});
      case 'cacheZip':return ok({files:Object.fromEntries(Object.entries(cacheFiles).map(([name,bytes])=>[name,bytes.toString('base64')]))});
      case 'cacheChildren':return ok({results:cacheBlocks,has_more:false});
      case 'cacheCreateUpload':uploadCounter++;return ok({id:'22222222-2222-4222-8222-'+String(uploadCounter).padStart(12,'0'),status:'pending'});
      case 'cacheSendUpload':return ok({id:state.cacheUploadId,status:'uploaded'});
      case 'cacheAppend':{const child=op.body.children[0];cacheBlocks=[...cacheBlocks,{...child,id:'11111111-1111-4111-8111-'+String(uploadCounter).padStart(12,'0')}];return ok({results:cacheBlocks});}
      case 'cacheGetFile':{const b=cacheBlocks.find(block=>op.url.endsWith(block.id));return ok({...b,parent:{type:'page_id',page_id:dailyPage.id},file:{...b.file,type:'file',file:{url:'https://prod-files-secure.s3.us-west-2.amazonaws.com/'+b.id+'/file?X-Amz-Date=20261002T100000Z&X-Amz-Expires=3600',expiry_time:'2026-10-02T11:00:00Z'}}});}
      case 'cacheDownload':return ok({bytes:cacheFiles[state.cacheEntries[state.cacheCursor||0].name].toString('base64')});
      case 'cachePromote':dailyPage={...dailyPage,properties:{...dailyPage.properties,...op.body.properties}};return ok(dailyPage);
      case 'cacheVerifyPage':return ok(dailyPage);
      case 'summaryRead':return ok({results:summaries,has_more:false});
      case 'appendSummary':summaries=[...summaries,...op.body.children];return ok({results:summaries});
      case 'finishNotion':dailyPage={...dailyPage,properties:{...dailyPage.properties,...op.body.properties}};return ok(dailyPage);
      case 'writeFailure':dailyPage={...dailyPage,properties:{...dailyPage.properties,...op.body.properties}};return ok(dailyPage);
      default:throw Error('unhandled_local_stage:'+stage);
    }
  }
  return {respond,requests,fixture:f,get snapshot(){return {rows,dailyPage,child,persisted,writes,liveAttempts};},seedDuplicate(){const props=stockProperties(f.payload.selectedStocks[0],f.payload);rows=[{id:'old',created_time:'2026-10-02T10:00:00Z',properties:props},{id:'new',created_time:'2026-10-02T10:01:00Z',properties:props}];}};
}
function run(environment,initial){let out=initial||start({marketDate:'2026-10-02',requestId:'local-test',mode:'screen',siteUrl:'https://stockscreener.andyshih.uk',owner:'local'},now);let steps=0;while(out.route!=='done'&&steps<200){const response=environment.respond(out);out=advance(out.state.stage==='cacheZip'?{...out.state,stage:'cacheArtifactBytes',cacheZipVerifiedHash:out.state.cacheArtifactSha256}:out.state,response,now+steps*1000);steps++;}assert.ok(steps<200);return out;}
test('full exact-run artifact flow creates daily record and inline database, verifies archive then deployment',()=>{
  const env=world({dispatch:true,pendingOnce:true,deployDelayed:true});const result=run(env);
  assert.equal(result.state.errorCategory,undefined);assert.equal(result.state.notionStatus,'complete');assert.equal(result.state.deployStatus,'verified');
  assert.equal(result.state.cacheStatus,'verified');assert.equal(result.state.cacheMetricsComplete,false);assert.equal(env.snapshot.dailyPage.properties['Cache Parts Verified'].number,12);
  assert.equal(env.snapshot.rows.length,1);assert.equal(env.snapshot.dailyPage.properties['Active Revision'].rich_text[0].text.content,'b'.repeat(12));
  assert.equal(env.requests.filter(op=>op.url.endsWith('/dispatches')).length,1);
  const db=env.requests.find(op=>op.url==='https://api.notion.com/v1/databases'&&op.method==='POST');
  assert.equal(db.body.is_inline,true);assert.deepEqual(db.body.initial_data_source.properties,stockSchema());
});
test('ambiguous Notion stock create re-reads row key before retry and leaves one row',()=>{
  const env=world({ambiguous:true});const result=run(env);assert.equal(result.state.notionStatus,'complete');
  assert.equal(env.snapshot.rows.length,1);assert.equal(env.requests.filter(op=>op.url==='https://api.notion.com/v1/pages'&&op.body.parent?.data_source_id==='child-source').length,1);
});
test('legitimate empty success creates empty complete daily child database',()=>{
  const env=world({zero:true});const result=run(env);assert.equal(result.state.notionStatus,'complete');assert.ok(env.snapshot.child);assert.equal(env.snapshot.rows.length,0);assert.equal(env.snapshot.dailyPage.properties['Expected Count'].number,0);
});
test('screening failure creates metadata record, never stock database or stock pages',()=>{
  const env=world({failure:true});const result=run(env);assert.equal(result.state.notionStatus,'failure_metadata');assert.equal(result.state.screeningStatus,'failed');assert.ok(env.snapshot.dailyPage);assert.equal(env.snapshot.child,null);assert.equal(env.snapshot.rows.length,0);assert.equal(env.snapshot.dailyPage.properties['Selected Count'],undefined);
});
test('holiday persists skip and makes no Actions or Notion writes',()=>{
  const env=world();const result=run(env,start({marketDate:'2026-10-09',requestId:'local-holiday',mode:'screen',siteUrl:'https://stockscreener.andyshih.uk',owner:'local'},now));
  assert.equal(result.state.screeningStatus,'skipped_non_trading');assert.equal(env.requests.some(op=>op.target==='notion'||op.url.includes('/actions/')),false);
});
test('identical revision duplicate cleanup preserves oldest valid stock row',()=>{
  const env=world();env.seedDuplicate();const result=run(env);assert.equal(result.state.notionStatus,'complete');assert.equal(env.snapshot.rows.length,1);assert.equal(env.snapshot.rows[0].id,'old');
});
test('new state branch creation follows independently verified main ref',()=>{
  const env=world({createBranch:true});const result=run(env);assert.equal(result.state.notionStatus,'complete');assert.equal(env.requests.filter(op=>op.url.endsWith('/git/refs')).length,1);
});
test('already complete same payload skips dispatch and all Notion writes',()=>{
  const env=world({existing:{requestId:'local-test',marketDate:'2026-10-02',owner:'prior',released:true,cacheStatus:'verified',screeningStatus:'complete',notionStatus:'complete',deployStatus:'verified'}});const result=run(env);
  assert.equal(result.state.screeningStatus,'already_complete');assert.equal(env.requests.some(op=>op.target==='notion'||op.method!=='GET'),false);
});
test('legacy archive reads authenticated pinned index/month/revision and archives real retained union without dispatch',()=>{
  const fs=require('node:fs');const path=require('node:path');const root=path.resolve(__dirname,'../../public');const env=world();let revisionRaw;
  const adapter={respond(output){const {stage}=output.state;
    if(stage==='legacyRef')return {statusCode:200,body:{object:{sha:'a'.repeat(40)}}};
    if(['legacyIndex','legacyMonth','legacyExport'].includes(stage)){
      assert.ok(output.op.url.endsWith('?ref='+'a'.repeat(40)));const file=output.op.url.split('/contents/public')[1].split('?')[0];const raw=fs.readFileSync(path.join(root,file),'utf8');if(stage==='legacyExport')revisionRaw=raw;
      return {statusCode:200,body:{encoding:'base64',size:Buffer.byteLength(raw),content:Buffer.from(raw).toString('base64')}};
    }
    if(['liveProbe','liveVerify'].includes(stage)){assert.ok(output.op.url.includes('/data/archive/v1/revisions/2026-09-08.'));return {statusCode:200,body:revisionRaw};}
    return env.respond(output);
  }};
  const result=run(adapter,start({marketDate:'2026-09-08',requestId:'legacy:2026-09-08',mode:'legacy_archive',runKind:'manual',siteUrl:'https://stockscreener.andyshih.uk',owner:'local'},now));
  assert.equal(result.state.notionStatus,'complete');assert.equal(result.state.deployStatus,'verified');assert.equal(result.state.archiveMethod,'legacy_archive');
  assert.equal(env.requests.some(op=>op.url.includes('/actions/')),false);
  const raw=JSON.parse(revisionRaw);const union=new Set(Object.values(raw.strategies).flatMap(rows=>rows.map(row=>row.code)));
  assert.equal(env.snapshot.rows.length,union.size);assert.equal(env.snapshot.dailyPage.properties['Quality'].rich_text[0].text.content,'legacy_archive');
  assert.equal(env.snapshot.dailyPage.properties['Actions URL'].url,null);
});
