const { createHash } = require('node:crypto');
let cache = {};
try { cache = require('./market-cache.cjs'); } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const date = '2026-10-02';
const prior = '2026-10-01';
const source = { requestId: 'stockscreener:20261002:v2', actionsRunId: '37094557187', sourceGitCommit: 'a'.repeat(40) };
const roles = [
  ['institutional_raw:TWSE', 'institutional_raw', 'TWSE'],
  ['institutional_raw:TPEx', 'institutional_raw', 'TPEx'],
  ['institutional_normalized:TWSE', 'institutional_normalized', 'TWSE'],
  ['institutional_normalized:TPEx', 'institutional_normalized', 'TPEx'],
  ['calendar_raw', 'calendar_raw', 'TWSE'], ['calendar_normalized', 'calendar_normalized', 'TWSE'],
  ['volume_raw', 'volume_raw', 'TWSE'], ['volume_normalized', 'volume_normalized', 'TWSE'],
  ['published_stock_inputs', 'published_stock_inputs', 'ALL'],
];
function fixture() {
  const raw = Buffer.from('exact official receipt\n0.0 中文');
  const groups = roles.map(([key, kind, market]) => {
    const codes = kind.startsWith('institutional') ? [market === 'TWSE' ? '2330' : '1240'] : kind.startsWith('volume') ? ['00631L'] : kind === 'published_stock_inputs' ? ['1240', '2330'] : [];
    const dates = kind.startsWith('institutional') || kind.startsWith('volume') ? [prior, date] : [date];
    let body = raw;
    if (kind === 'institutional_normalized') body = { rows: dates.flatMap(marketDate => codes.map(code => ({ marketDate, code, buy: 0, sell: 1000, net: -1000, unit: 'shares' }))) };
    if (kind === 'volume_normalized') body = { rows: dates.map(marketDate => ({ marketDate, code: '00631L', volume: marketDate === prior ? 0 : 2000, unit: 'shares' })) };
    if (kind === 'calendar_normalized') body = { year: 2026, timezone: 'Asia/Taipei', closedDates: ['2026-10-09'], openExceptions: ['2026-02-23'] };
    if (kind === 'published_stock_inputs') body = { rows: codes.map(code => ({ marketDate: date, code, metrics: { currentPrice: code === '1240' ? 0 : 100, currentPeg: null } })) };
    return { key, kind, market, codes, dates, ...(kind.startsWith('institutional') ? { codesByDate: Object.fromEntries(dates.map(marketDate => [marketDate, [...codes]])) } : {}), unit: kind.startsWith('calendar') ? 'calendar' : kind === 'published_stock_inputs' ? 'mixed' : 'shares', sourceUrl: 'https://openapi.twse.com.tw/v1/example', sourceSha256: hash(raw), normalizedFromSha256: kind.endsWith('_normalized') ? hash(raw) : null, body };
  });
  const expected = { marketDate: date, previousTradingDate: prior, source, metricKeys: ['currentPrice', 'currentPeg'], calendarYear: 2026, groups: groups.map(({ body, ...group }) => group) };
  const input = { marketDate: date, previousTradingDate: prior, generatedAt: '2026-10-03T04:00:00Z', source, groups };
  return { input, expected };
}
function built(input = fixture().input, limits) { return cache.buildMarketCache(input, limits); }
function fixtureCrc(bytes){let crc=0xffffffff;for(const b of bytes){crc^=b;for(let bit=0;bit<8;bit++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}return (crc^0xffffffff)>>>0;}
function zipFixture(entries){const locals=[],centrals=[];let offset=0;for(const [name,data,attributes=0,descriptor=false,declared]of entries){const bytes=Buffer.isBuffer(data)?data:Buffer.alloc(data),size=declared??bytes.length,crc=fixtureCrc(bytes),n=Buffer.from(name),local=Buffer.alloc(30);local.writeUInt32LE(0x04034b50);local.writeUInt16LE(descriptor?8:0,6);if(!descriptor){local.writeUInt32LE(crc,14);local.writeUInt32LE(size,18);local.writeUInt32LE(size,22);}local.writeUInt16LE(n.length,26);const dd=Buffer.alloc(descriptor?(descriptor==='bare'?12:16):0);if(descriptor){const at=descriptor==='bare'?0:4;if(at)dd.writeUInt32LE(0x08074b50);dd.writeUInt32LE(crc,at);dd.writeUInt32LE(size,at+4);dd.writeUInt32LE(size,at+8);}const block=Buffer.concat([local,n,bytes,dd]);locals.push(block);const central=Buffer.alloc(46);central.writeUInt32LE(0x02014b50);central.writeUInt16LE(descriptor?8:0,8);central.writeUInt32LE(crc,16);central.writeUInt32LE(size,20);central.writeUInt32LE(size,24);central.writeUInt16LE(n.length,28);central.writeUInt32LE(attributes>>>0,38);central.writeUInt32LE(offset,42);centrals.push(Buffer.concat([central,n]));offset+=block.length;}const central=Buffer.concat(centrals),end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(entries.length,8);end.writeUInt16LE(entries.length,10);end.writeUInt32LE(central.length,12);end.writeUInt32LE(offset,16);return Buffer.concat([...locals,central,end]);}

function artifact(){const f=fixture();const latest=Buffer.from(JSON.stringify({marketDate:date,runId:'fixture-release',stocks:[{code:'1240'},{code:'2330'}]}));const groups=f.input.groups.map(g=>g.kind==='published_stock_inputs'?{...g,sourceSha256:hash(latest)}:g);const expected={...f.expected,groups:groups.map(({body,...g})=>g)};const bundle=built({...f.input,groups});const checked=require('./market-cache.cjs').verifyMarketCache(bundle.manifest,bundle.files,{...expected,manifestHash:bundle.manifest.manifestHash});const proof={schemaVersion:'market-cache-producer-proof-v1',semanticValidation:'bounded-python-v1',marketDate:date,previousTradingDate:prior,source,...checked};const members={'manifest.json':Buffer.from(JSON.stringify(bundle.manifest)),'proof.json':Buffer.from(JSON.stringify(proof)),'expected.json':Buffer.from(JSON.stringify(expected)),...bundle.files};return {latest,members,bundle,expected,fingerprint:{schemaVersion:'publication-fingerprint-v1',marketDate:date,runId:'fixture-release',contentHash:hash(latest)}};}
module.exports={artifact,fixture,built,date,prior,source,hash,zipFixture,fixtureCrc};
