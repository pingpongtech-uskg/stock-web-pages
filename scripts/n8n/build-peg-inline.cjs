'use strict';
// Integrates native discovery into the Stockscreener canvas; no child workflow or PEG dispatch.
const fs = require('node:fs');
const path = require('node:path');
const folder = __dirname;
function source(file, name) {
  return `const ${name}=(()=>{const module={exports:{}};\n${fs.readFileSync(path.join(folder,file),'utf8')}\nreturn module.exports;})();`;
}
function installPegInline({add, code, connect, advanceNode}) {
  const child = JSON.parse(fs.readFileSync(path.join(folder,'peg-source-discovery.workflow.json'),'utf8'));
  function copy(name) {
    const old=child.nodes.find(node=>node.name===name);
    if(!old)throw Error('inline_node_missing:'+name);
    const node=add(old.name,old.type,old.typeVersion,structuredClone(old.parameters),undefined,{...(old.onError?{onError:old.onError}:{}),...(old.retryOnFail===false?{retryOnFail:false}:{})});
    if(old.credentials)node.credentials=structuredClone(old.credentials);
    return node;
  }
  const peg=source('peg-source-discovery.cjs','Peg');
  const pub=source('peg-publication-state.cjs','Pub');
  const contract=source('peg-candidate-contract.cjs','Contract');
  const state=`$('Capture PEG discovery parent state').first().json.state`;
  const entry=code('Capture PEG discovery parent state',`return [{json:{state:$input.first().json.state}}];`);
  const get=copy('Read durable PEG progress');get.alwaysOutputData=true;
  const lease=code('Prepare discovery lease',`${pub}\nconst input=$input.first().json;const state=${state};
let old;try{old=JSON.parse(input.state_json||'{}')}catch{return [{json:{claimReady:false,reason:'peg_state_invalid'}}]}
// Old standalone dispatch intents do not authorize or suppress this candidate.
const row={...input,state_json:JSON.stringify({...old,dispatchIntent:null})};
const result=Pub.claim(row,{marketDate:state.marketDate,owner:String($execution.id),now:Date.now(),reserveBrave:Boolean(input.searx_url)});
return [{json:{...result,claimReady:result.status==='claimed'}}];`);
  const leaseReady=copy('Discovery lease available?');
  const claim=copy('Claim PEG progress with CAS');claim.alwaysOutputData=true;
  const verify=code('Verify discovery lease',`const row=$input.first().json;let stored;try{stored=JSON.parse(row.state_json)}catch{return [{json:{leaseValid:false}}]}
return [{json:{...row,leaseValid:stored.leaseOwner===String($execution.id)&&Number(row.lease_until)>Date.now()}}];`);
  const verifyReady=copy('Discovery lease available?'); verifyReady.name='Discovery claim verified?'; verifyReady.parameters.conditions.conditions[0].leftValue='={{ $json.leaseValid === true }}';
  const registry=copy('Fetch issuer registry');
  const init=code('Initialize PEG source discovery',`${peg}\nconst state=${state};const registry=$input.first().json;
let issuers={};try{const b=registry.body;issuers=JSON.parse(Buffer.from(b.content,'base64').toString('utf8'));issuers=issuers.issuers||issuers.companies||issuers}catch{}
const row=$('Verify discovery lease').first().json;const persisted=JSON.parse(row.state_json);
const unavailable=()=>{const stocks=state.pegPreview.stocks.filter(s=>(s.pegDiscoveryRequired===true||s.pegReview.status==='needs_review')).map(s=>({code:s.code,name:s.name,legalName:s.name,officialDomains:[],results:[],reason:'source_unavailable'}));return [{json:{initReady:false,state:{outcome:'provider_unavailable',manifest:{marketDate:state.marketDate,requestId:state.requestId,generatedAt:new Date().toISOString(),searchUsage:{date:state.marketDate,brave:persisted.braveUsage.used},stocks}}}}]};
if(registry.statusCode!==200||!Object.keys(issuers).length||!String(row.searx_url||''))return unavailable();
const cachedManifest={...(persisted.cachedManifest||{}),searchUsage:{date:state.marketDate,brave:persisted.braveUsage.used}};
const config={marketDate:state.marketDate,requestId:state.requestId,candidateSha256:state.pegCandidateSha256,searxBaseUrl:String(row.searx_url||''),braveDailyLimit:20};
const discovery=Peg.init({latest:state.pegPreview,issuers,cachedManifest,config});
return discovery.outcome==='configuration_required'?unavailable():[{json:{initReady:true,state:discovery}}];`);
  const initReady=copy('Source commit ready?');initReady.name='PEG issuer registry verified?';initReady.parameters.conditions.conditions[0].leftValue='={{ $json.initReady === true }}';
  const plan=copy('Plan next provider'), complete=copy('Discovery complete?'), provider=copy('Use SearxNG?');
  const searx=copy('Search with SearxNG'), brave=copy('Search with Brave'), apply=copy('Apply provider response');
  const finish=code('Finish PEG manifest',`${contract}\nconst item=$input.first().json;const discovery=item.state||item;const parent=${state};
if(discovery.outcome==='configuration_required'||!discovery.manifest)return [{json:{manifestReady:false}}];
try{return [{json:{...Contract.bindManifest(discovery.manifest,parent.pegPreview),manifestReady:true}}]}catch{return [{json:{manifestReady:false}}]};`);
  const manifestReady=copy('Source commit ready?');manifestReady.name='PEG manifest complete?';manifestReady.parameters.conditions.conditions[0].leftValue='={{ $json.manifestReady === true }}';
  const savePlan=copy('Prepare durable search results'), saveReady=copy('Search results ready?'), save=copy('Persist search results with CAS');save.alwaysOutputData=true;
  const saveVerify=code('Verify saved PEG search results',`const row=$input.first().json;let data;try{data=JSON.parse(row.state_json)}catch{};const state=${state};return [{json:{valid:data?.leaseOwner===String($execution.id)&&data.cachedManifest?.candidateSha256===state.pegCandidateSha256&&data.cachedManifest?.requestId===state.requestId}}];`);
  const savedReady=copy('Source commit ready?');savedReady.name='PEG search results saved?';savedReady.parameters.conditions.conditions[0].leftValue='={{ $json.valid === true }}';
  const read=copy('Read current source manifest SHA'); read.parameters.url='https://api.github.com/repos/pingpongtech-uskg/stock-web-pages/contents/config/peg_search_results.json?ref=n8n-state';
  const putPlan=code('Prepare source manifest commit',`const response=$input.first().json;const row=$('Persist search results with CAS').first().json;let stored;try{stored=JSON.parse(row.state_json)}catch{return [{json:{ready:false}}]}
const manifest=stored.cachedManifest;const status=Number(response.statusCode);const sha=response.body?.sha;
if(!manifest||![200,404].includes(status)||(status===200&&!/^[a-f0-9]{40}$/.test(sha||'')))return [{json:{ready:false}}];
return [{json:{ready:true,body:{message:'[CF-Pages-Skip] chore: pin PEG discovery manifest',branch:'n8n-state',content:Buffer.from(JSON.stringify(manifest)).toString('base64'),...(sha?{sha}:{})}}}];`);
  const putReady=copy('Source commit ready?'); putReady.parameters.conditions.conditions[0].leftValue='={{ $json.ready === true }}';
  const put=copy('Commit approved source manifest');
  const receipt=code('Verify pinned PEG source commit',`const response=$input.first().json;const commit=response.body?.commit?.sha;
if(![200,201].includes(Number(response.statusCode))||!/^[a-f0-9]{40}$/.test(commit||''))return [{json:{ok:false}}];
return [{json:{ok:true,manifestCommit:commit}}];`);
  const receiptReady=copy('Source commit ready?');receiptReady.name='PEG manifest commit verified?';receiptReady.parameters.conditions.conditions[0].leftValue='={{ $json.ok === true }}';
  const releasePlan=code('Release discovery quota lease',`${pub}\nconst receipt=$input.first().json;const row=$('Persist search results with CAS').first().json;const stored=JSON.parse(row.state_json);
const result=Pub.finish(row,{marketDate:stored.marketDate,owner:String($execution.id),now:Date.now(),actualBraveUsed:stored.braveUsage.used,manifest:stored.cachedManifest,releaseLease:true});
return [{json:{...result,manifestCommit:receipt.manifestCommit,ready:result.status==='finished'}}];`);
  const releaseReady=copy('Source commit ready?');releaseReady.name='PEG lease release ready?';releaseReady.parameters.conditions.conditions[0].leftValue='={{ $json.ready === true }}';
  const release=copy('Save final PEG outcome with CAS');release.alwaysOutputData=true;
  const success=code('Return pinned PEG manifest to main',`const row=$input.first().json;let stored;try{stored=JSON.parse(row.state_json)}catch{stored={}}
const plan=$('Release discovery quota lease').first().json;const ok=stored.leaseOwner===null&&Number(row.lease_until)===0;
return [{json:{state:${state},response:ok?{statusCode:200,body:{manifestCommit:plan.manifestCommit}}:{statusCode:400,body:{message:'peg_lease_release_failed'}}}}];`);
  const failure=code('Prepare failed PEG quota release',`let row;
for(const name of ['Persist search results with CAS','Verify discovery lease']){try{if($(name).isExecuted){const all=$(name).all();if(all.length){row=all[all.length-1].json;break}}}catch{}}
let previous;try{previous=JSON.parse(row.state_json)}catch{}
if(!previous||previous.leaseOwner!==String($execution.id)||Number(row.lease_until)<=Date.now())return [{json:{release:false}}];
const usage=previous.braveUsage||{};const used=Number(usage.used)||0;const reserved=Number(usage.reserved)||0;
const next={...previous,leaseOwner:null,leaseBraveReservation:0,braveUsage:{...usage,used:used+reserved,reserved:0},lastOutcome:'discovery_failed'};
return [{json:{release:true,expectedRevision:row.revision,row:{id:1,revision:row.revision+1,lease_until:0,state_json:JSON.stringify(next)}}}];`);
  const failureReady=copy('Source commit ready?');failureReady.name='Failed PEG lease needs release?';failureReady.parameters.conditions.conditions[0].leftValue='={{ $json.release === true }}';
  const failureRelease=copy('Save final PEG outcome with CAS');failureRelease.name='Release failed PEG quota lease with CAS';failureRelease.alwaysOutputData=true;
  const failureResult=code('Stop on PEG discovery failure',`return [{json:{state:${state},response:{statusCode:400,body:{message:'peg_discovery_failed'}}}}];`);
  connect(entry,get);connect(get,lease);connect(lease,leaseReady);connect(leaseReady,claim,0);connect(leaseReady,failure,1);connect(claim,verify);connect(verify,verifyReady);connect(verifyReady,registry,0);connect(verifyReady,failure,1);connect(registry,init);connect(init,initReady);connect(initReady,plan,0);connect(initReady,finish,1);connect(plan,complete);connect(complete,finish,0);connect(complete,provider,1);connect(provider,searx,0);connect(provider,brave,1);connect(searx,apply);connect(brave,apply);connect(apply,plan);connect(finish,manifestReady);connect(manifestReady,savePlan,0);connect(manifestReady,failure,1);connect(savePlan,saveReady);connect(saveReady,save,0);connect(saveReady,failure,1);connect(save,saveVerify);connect(saveVerify,savedReady);connect(savedReady,read,0);connect(savedReady,failure,1);connect(read,putPlan);connect(putPlan,putReady);connect(putReady,put,0);connect(putReady,failure,1);connect(put,receipt);connect(receipt,receiptReady);connect(receiptReady,releasePlan,0);connect(receiptReady,failure,1);connect(releasePlan,releaseReady);connect(releaseReady,release,0);connect(releaseReady,failure,1);connect(release,success);connect(success,advanceNode);connect(failure,failureReady);connect(failureReady,failureRelease,0);connect(failureReady,failureResult,1);connect(failureRelease,failureResult);connect(failureResult,advanceNode);
  return {entry};
}
module.exports={installPegInline};
