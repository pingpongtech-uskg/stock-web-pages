'use strict';
const fs = require('node:fs');
const path = require('node:path');
const folder = __dirname;
const source = fs.readFileSync(path.join(folder, 'peg-source-discovery.cjs'), 'utf8');
const machine = `const Peg=(()=>{const module={exports:{}};\n${source}\nreturn module.exports;})();`;
const nodes = [];
const connections = {};
function add(name, type, typeVersion, parameters, extra = {}) {
  const node = { name, type, typeVersion, parameters, position: [nodes.length * 240, 0], ...extra };
  nodes.push(node);
  return node;
}
function code(name, jsCode) {
  return add(name, 'n8n-nodes-base.code', 2, { mode: 'runOnceForAllItems', jsCode });
}
function link(from, to, branch = 0) {
  connections[from.name] ||= { main: [] };
  connections[from.name].main[branch] ||= [];
  connections[from.name].main[branch].push({ node: to.name, type: 'main', index: 0 });
}
function httpOptions(responseFormat = 'json') {
  return { timeout: 15000, redirect: { redirect: { followRedirects: false } }, response: { response: { fullResponse: true, neverError: true, responseFormat } } };
}
function http(name, url, { credential, headers = false } = {}) {
  const parameters = {
    method: 'GET', url, authentication: credential ? 'predefinedCredentialType' : 'none',
    ...(credential ? { nodeCredentialType: credential } : {}), sendHeaders: headers,
    ...(headers ? { headerParameters: { parameters: [
      { name: 'Accept', value: 'application/vnd.github+json' },
      { name: 'X-GitHub-Api-Version', value: '2022-11-28' },
    ] } } : {}),
    sendBody: false, options: httpOptions('json'),
  };
  const extra = { retryOnFail: false, onError: 'continueRegularOutput' };
  if (credential === 'githubApi') extra.credentials = { githubApi: { id: 'F0VoGrfOT4OTl2o8', name: 'GitHub_StockScreener' } };
  if (credential === 'braveSearchApi') extra.credentials = { braveSearchApi: { id: 'keND4ReyUl49IW5p', name: 'Brave Search API' } };
  return add(name, 'n8n-nodes-base.httpRequest', 4.5, parameters, extra);
}
const manual = add('Manual Trigger', 'n8n-nodes-base.manualTrigger', 1, {});
const execute = add('Execute Workflow Trigger', 'n8n-nodes-base.executeWorkflowTrigger', 1.1, { inputSource: 'passthrough' });
const latest = http('Fetch public latest.json', 'https://stockscreener.andyshih.uk/data/latest.json');
const registry = http('Fetch issuer registry', 'https://api.github.com/repos/pingpongtech-uskg/stock-web-pages/contents/config/peg_issuer_domains.json?ref=main', { credential: 'githubApi', headers: true });
const init = code('Initialize PEG source discovery', `${machine}
const latestResponse=$('Fetch public latest.json').first().json||{};
let latest=latestResponse.body||{};
if(typeof latest==='string'){try{latest=JSON.parse(latest)}catch{latest={}}}
const registryResponse=$('Fetch issuer registry').first().json||{};
let issuers={};
try{const body=registryResponse.body||{};const decoded=body.content?JSON.parse(Buffer.from(body.content,'base64').toString('utf8')):{};issuers=decoded.issuers||decoded.companies||decoded}catch{}
const staticData=$getWorkflowStaticData('global');
const cached=staticData.pegSourceManifest||null;
const usage=staticData.pegSourceUsage||cached?.searchUsage||null;
const cachedManifest=cached?{...cached,...(usage?{searchUsage:usage}:{})}:usage?{marketDate:usage.date,searchUsage:usage}:null;
const marketDate=String(latest.marketDate||'');
const config={marketDate,requestId:'peg-'+marketDate+'-ttm-v1',searxBaseUrl:String(row.searx_url||''),braveDailyLimit:20};
const state=Peg.init({latest,issuers,cachedManifest,config});
if(registryResponse.statusCode!==200||!Object.keys(issuers).length){state.stocks=[];state.outcome='provider_search_fatal';}
return [{json:{state}}];`);
const plan = code('Plan next provider', `${machine}
const incoming=$input.first().json||{};
const state=incoming.state||incoming;
return [{json:Peg.plan(state,new Date().toISOString())}];`);
function ifNode(name, leftValue, rightValue, operator = 'true') {
  const condition = { leftValue, rightValue, operator: { type: 'boolean', operation: operator, singleValue: true } };
  return add(name, 'n8n-nodes-base.if', 2.2, { conditions: { options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 }, conditions: [condition], combinator: 'and' } });
}
const done = ifNode('Discovery complete?', '={{ $json.done }}', true, 'true');
const route = ifNode('Use SearxNG?', '={{ $json.action.provider === "searx" }}', true, 'true');
const searx = http('Search with SearxNG', '={{ $json.action.url }}');
const brave = http('Search with Brave', '={{ $json.action.url }}', { credential: 'braveSearchApi' });
brave.parameters.sendHeaders=true;
brave.parameters.headerParameters={parameters:[{name:'Accept',value:'application/json'}]};
const apply = code('Apply provider response', `${machine}
const planned=$('Plan next provider').last().json;
const raw=$input.first().json||{};
const response={statusCode:Number(raw.statusCode??raw.status)||0,body:raw.body,headers:raw.headers||{},error:raw.error};
return [{json:Peg.apply(planned.state,planned.action.provider,response,new Date().toISOString())}];`);
const finish = code('Finish PEG manifest', `${machine}
const item=$input.first().json||{};
const state=item.state||item;
const manifest=state.manifest||null;
const staticData=$getWorkflowStaticData('global');
if(manifest){staticData.pegSourceManifest=manifest;staticData.pegSourceUsage=manifest.searchUsage||{date:state.config?.marketDate||null,brave:state.braveUsed||0};}
const outcome=state.outcome||'complete';
const message=outcome==='configuration_required'?'PEG source discovery skipped: SearxNG base URL is not configured.':'PEG source discovery complete.';
return [{json:manifest?{...manifest,outcome,message}:{outcome,message}}];`);
link(manual, latest); link(execute, latest); link(latest, registry); link(registry, init); link(init, plan); link(plan, done);
link(done, finish, 0); link(done, route, 1); link(route, searx, 0); link(route, brave, 1); link(searx, apply); link(brave, apply); link(apply, plan);
const publicationSource = fs.readFileSync(path.join(folder, 'peg-publication-state.cjs'), 'utf8');
const publication = `const Pub=(()=>{const module={exports:{}};\n${publicationSource}\nreturn module.exports;})();`;
const api = 'https://api.github.com/repos/pingpongtech-uskg/stock-web-pages';
const tableId = 'GekfbPgv3ib29FPq';
const tableLocator = { __rl: true, mode: 'id', value: tableId };
function progressGet(name) {
  return add(name, 'n8n-nodes-base.dataTable', 1.1, { resource: 'row', operation: 'get', dataTableId: tableLocator, matchType: 'allConditions', filters: { conditions: [{ keyName: 'id', condition: 'eq', keyValue: '1' }] }, returnAll: false, limit: 1 });
}
function progressUpdate(name) {
  return add(name, 'n8n-nodes-base.dataTable', 1.1, {
    resource: 'row', operation: 'update', dataTableId: tableLocator, matchType: 'allConditions',
    filters: { conditions: [{ keyName: 'id', condition: 'eq', keyValue: '1' }, { keyName: 'revision', condition: 'eq', keyValue: '={{ $json.expectedRevision }}' }] },
    columns: { mappingMode: 'defineBelow', value: { state_json: '={{ $json.row.state_json }}', revision: '={{ $json.row.revision }}', lease_until: '={{ $json.row.lease_until }}' }, matchingColumns: [], schema: [
      { id: 'state_json', displayName: 'state_json', type: 'string', display: true },
      { id: 'revision', displayName: 'revision', type: 'number', display: true },
      { id: 'lease_until', displayName: 'lease_until', type: 'number', display: true },
    ] }, options: {},
  }, { retryOnFail: false });
}
function githubWrite(name, method, suffix) {
  const result = http(name, api + suffix, { credential: 'githubApi', headers: true });
  result.parameters = { ...result.parameters, method, sendBody: true, specifyBody: 'json', jsonBody: '={{ $json.body }}' };
  return result;
}
const readProgress = progressGet('Read durable PEG progress');
const prepareLease = code('Prepare discovery lease', `${publication}
const latestResponse=$('Fetch public latest.json').first().json;
const value=latestResponse.body;
if(latestResponse.statusCode!==200||!value||!Array.isArray(value.stocks))return [{json:{outcome:'public_data_unavailable',claimReady:false}}];
if(!String($input.first().json.searx_url||''))return [{json:{outcome:'configuration_required',claimReady:false}}];
let expectedDate;
try{if($('Execute Workflow Trigger').isExecuted)expectedDate=$('Execute Workflow Trigger').first().json.marketDate}catch{}
if(expectedDate&&expectedDate!==value.marketDate)return [{json:{outcome:'public_date_pending'}}];
const result=Pub.claim($input.first().json,{marketDate:value.marketDate,owner:String($execution.id),now:Date.now()});
return [{json:{...result,claimReady:result.status==='claimed'}}];`);
const claimReady = ifNode('Discovery lease available?', '={{ $json.claimReady === true }}', true);
const claimCAS = progressUpdate('Claim PEG progress with CAS');
const verifyLease = code('Verify discovery lease', `const row=$input.first().json;let state;try{state=JSON.parse(row.state_json)}catch{return []}
if(state.leaseOwner!==String($execution.id)||Number(row.lease_until)<=Date.now())return [];
return [{json:row}];`);
const readRuns = http('Read exact PEG Actions requests', api + '/actions/workflows/peg.yml/runs?per_page=100', { credential: 'githubApi', headers: true });
const checkRuns = code('Check existing PEG request', `${publication}
const response=$input.first().json;
const row=$('Verify discovery lease').first().json;const state=JSON.parse(row.state_json);
const runs=response.body?.workflow_runs;
const title='PEG repair | '+state.requestId+' | '+state.marketDate;
const matching=Array.isArray(runs)?runs.filter(r=>r.display_title===title):[];
const searchRequired=response.statusCode===200&&Array.isArray(runs)&&!matching.length&&!state.dispatchIntent;
return [{json:{searchRequired,outcome:response.statusCode!==200?'actions_unavailable':matching.length?'existing_request':state.dispatchIntent?'dispatch_uncertain':'search_required'}}];`);
const needSearch = ifNode('Search required?', '={{ $json.searchRequired }}', true);
const readReview = http('Read public PEG publication proof', 'https://stockscreener.andyshih.uk/data/peg-review.json');
const existingResult = code('Evaluate existing PEG publication', `${publication}
const row=$('Verify discovery lease').first().json;const state=JSON.parse(row.state_json);
const result=Pub.plan({marketDate:state.marketDate,manifest:state.cachedManifest||{marketDate:state.marketDate,stocks:[]},latest:$('Fetch public latest.json').first().json,workflowRuns:$('Read exact PEG Actions requests').first().json.body,review:$input.first().json});
const prior=$('Check existing PEG request').first().json;
return [{json:{outcome:prior.outcome==='existing_request'?result.status:prior.outcome,run:result.run,runId:result.runId}}];`);
const persistSearchPlan = code('Prepare durable search results', `${publication}
const manifest=$input.first().json;
const row=$('Verify discovery lease').first().json;
const result=Pub.finish(row,{marketDate:manifest.marketDate,owner:String($execution.id),now:Date.now(),actualBraveUsed:manifest.searchUsage?.brave||0,manifest,releaseLease:false});
return result.status==='finished'?[{json:result}]:[{json:{outcome:result.status}}];`);
const searchSavedReady = ifNode('Search results ready?', '={{ $json.status === \"finished\" }}', true);
const saveSearch = progressUpdate('Persist search results with CAS');
const readContents = http('Read current source manifest SHA', api + '/contents/config/peg_search_results.json?ref=main', { credential: 'githubApi', headers: true });
const planPut = code('Prepare source manifest commit', `${publication}
const row=$('Persist search results with CAS').first().json;const state=JSON.parse(row.state_json);
const result=Pub.plan({marketDate:state.marketDate,manifest:state.cachedManifest,latest:$('Fetch public latest.json').first().json,workflowRuns:$('Read exact PEG Actions requests').first().json.body,contentsResponse:$input.first().json});
const body=result.status==='manifest_publish_ready'?{message:result.message,branch:'main',content:Buffer.from(result.content,'utf8').toString('base64'),...(result.expectedSha?{sha:result.expectedSha}:{})}:null;
return [{json:{...result,body,outcome:result.status}}];`);
const putReady = ifNode('Source commit ready?', '={{ $json.status === "manifest_publish_ready" }}', true);
const putManifest = githubWrite('Commit approved source manifest', 'PUT', '/contents/config/peg_search_results.json');
const refreshRuns = http('Recheck PEG request before dispatch', api + '/actions/workflows/peg.yml/runs?per_page=100', { credential: 'githubApi', headers: true });
const planDispatch = code('Prepare PEG Actions dispatch', `${publication}
const response=$input.first().json;if(response.statusCode!==200||!Array.isArray(response.body?.workflow_runs))return [{json:{outcome:'actions_unavailable'}}];
const row=$('Persist search results with CAS').first().json;const state=JSON.parse(row.state_json);
const result=Pub.plan({marketDate:state.marketDate,manifest:state.cachedManifest,latest:$('Fetch public latest.json').first().json,workflowRuns:$('Read exact PEG Actions requests').first().json.body,manifestPutResponse:$('Commit approved source manifest').first().json,workflowRunsAfterPut:response.body});
return [{json:{...result,outcome:result.status,body:result.action?.body}}];`);
const dispatchReady = ifNode('PEG dispatch ready?', '={{ $json.status === "dispatch_ready" }}', true);
const intentPlan = code('Prepare durable dispatch intent', `${publication}
const plan=$input.first().json;const row=$('Persist search results with CAS').first().json;const state=JSON.parse(row.state_json);
const result=Pub.recordDispatchIntent(row,{marketDate:state.marketDate,owner:String($execution.id),now:Date.now(),manifestCommitSha:plan.manifestCommitSha});
return result.status==='dispatch_intent_recorded'?[{json:result}]:[];`);
const saveIntent = progressUpdate('Persist dispatch intent with CAS');
const dispatchBody = code('Load pinned PEG dispatch body', `return [{json:{body:$('Prepare PEG Actions dispatch').first().json.body}}];`);
const sendDispatch = githubWrite('Dispatch PEG enrichment once', 'POST', '/actions/workflows/peg.yml/dispatches');
sendDispatch.parameters.options.response.response.responseFormat = 'text';
const receipt = code('Evaluate PEG dispatch receipt', `const response=$input.first().json;return [{json:{outcome:response.statusCode===204?'dispatch_accepted':'dispatch_uncertain',publicationVerified:false}}];`);
const finalPlan = code('Prepare final PEG progress', `let row;
for(const name of ['Persist dispatch intent with CAS','Persist search results with CAS','Verify discovery lease']){if($(name).isExecuted){const values=$(name).all();if(values.length){row=values[values.length-1].json;break}}}
if(!row)return [];
const previous=JSON.parse(row.state_json);if(previous.leaseOwner!==String($execution.id))return [];
const result=$input.first().json;const noProviderCalls=!$('Initialize PEG source discovery').isExecuted;const state={...previous,...(noProviderCalls?{braveUsage:{...previous.braveUsage,reserved:0},leaseBraveReservation:0}:{}),leaseOwner:null,lastOutcome:result.outcome||result.status||'unknown',lastResult:result,lastCheckedAt:Date.now()};
if(state.lastOutcome==='publication_complete')state.publicationVerified=true;
return [{json:{expectedRevision:row.revision,row:{id:1,revision:row.revision+1,lease_until:0,state_json:JSON.stringify(state)}}}];`);
const finalSave = progressUpdate('Save final PEG outcome with CAS');
const finalShow = code('Show PEG recovery outcome', `const input=$input.first().json;let state={};try{state=JSON.parse(input.state_json||'{}')}catch{}
return [{json:{outcome:state.lastOutcome||input.outcome||input.status||'skipped',marketDate:state.marketDate,requestId:state.requestId,braveUsed:state.braveUsage?.used,publicationVerified:state.publicationVerified===true,run:state.lastResult?.run}}];`);
init.parameters.jsCode = init.parameters.jsCode.replace(/const staticData=\$getWorkflowStaticData\('global'\);[\s\S]*?const marketDate=/, `const row=$('Verify discovery lease').first().json;const persisted=JSON.parse(row.state_json);
const cached=persisted.cachedManifest||null;
const usage={date:persisted.marketDate,brave:persisted.braveUsage.used};
const cachedManifest={...(cached||{}),searchUsage:usage};
const marketDate=`);
finish.parameters.jsCode = `${machine}
const item=$input.first().json;const state=item.state||item;
return [{json:{...state.manifest,outcome:state.outcome||'complete'}}];`;
connections[latest.name] = { main: [[{ node: readProgress.name, type: 'main', index: 0 }]] };
connections[registry.name] = { main: [[{ node: readRuns.name, type: 'main', index: 0 }]] };
link(readProgress, prepareLease);link(prepareLease, claimReady);link(claimReady, claimCAS, 0);link(claimReady, finalShow, 1);link(claimCAS, verifyLease);link(verifyLease, registry);
link(readRuns, checkRuns);link(checkRuns, needSearch);link(needSearch, init, 0);link(needSearch, readReview, 1);link(readReview, existingResult);link(existingResult, finalPlan);
link(finish, persistSearchPlan);link(persistSearchPlan, searchSavedReady);link(searchSavedReady, saveSearch, 0);link(searchSavedReady, finalPlan, 1);link(saveSearch, readContents);link(readContents, planPut);link(planPut, putReady);link(putReady, putManifest, 0);link(putReady, finalPlan, 1);
link(putManifest, refreshRuns);link(refreshRuns, planDispatch);link(planDispatch, dispatchReady);link(dispatchReady, intentPlan, 0);link(dispatchReady, finalPlan, 1);link(intentPlan, saveIntent);link(saveIntent, dispatchBody);link(dispatchBody, sendDispatch);link(sendDispatch, receipt);link(receipt, finalPlan);
link(finalPlan, finalSave);link(finalSave, finalShow);

const workflow = {
  name: 'Stockscreener PEG source discovery', active: false, nodes, connections,
  settings: { timezone: 'Asia/Taipei', executionOrder: 'v1', saveExecutionProgress: false, saveManualExecutions: false, saveDataErrorExecution: 'none', saveDataSuccessExecution: 'none' },
};
fs.writeFileSync(path.join(folder, 'peg-source-discovery.workflow.json'), JSON.stringify(workflow, null, 2) + '\n');
console.log(JSON.stringify({ nodes: nodes.length, output: 'peg-source-discovery.workflow.json' }));
