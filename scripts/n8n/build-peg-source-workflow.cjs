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
const dailyRunId=String(latest.runId||latest.actionsRunId||'unknown');
const config={marketDate,requestId:'peg-'+marketDate+'-'+dailyRunId,searxBaseUrl:'',braveDailyLimit:20};
const state=Peg.init({latest,issuers,cachedManifest,config});
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
const workflow = {
  name: 'Stockscreener PEG source discovery', active: false, nodes, connections,
  settings: { timezone: 'Asia/Taipei', executionOrder: 'v1', saveExecutionProgress: false, saveManualExecutions: false, saveDataErrorExecution: 'none', saveDataSuccessExecution: 'none' },
};
fs.writeFileSync(path.join(folder, 'peg-source-discovery.workflow.json'), JSON.stringify(workflow, null, 2) + '\n');
console.log(JSON.stringify({ nodes: nodes.length, output: 'peg-source-discovery.workflow.json' }));
