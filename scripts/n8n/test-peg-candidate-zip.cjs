'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {zipFixture, hash} = require('./cache-fixture.cjs');
const {extractPreviewZip} = require('./peg-candidate-zip.cjs');
const tar=Buffer.from('frozen candidate');
const preview=Buffer.from(JSON.stringify({candidateSha256:hash(tar),candidateBytes:tar.length,stocks:[{code:'2330'}]}));
const archive=(members=[['preview.json',preview]])=>zipFixture(members);
const context=bytes=>({artifactBytes:bytes.length,artifactSha256:hash(bytes)});
test('authenticates the exact preview-only ZIP and preserves the bound final candidate digest',()=>{
  const bytes=archive();
  assert.deepEqual(extractPreviewZip(bytes,context(bytes)),JSON.parse(preview));
  for(const descriptor of [true,'bare']) {
    const described=archive([['preview.json',preview,0,descriptor]]);
    assert.deepEqual(extractPreviewZip(described,context(described)),JSON.parse(preview));
  }
});
test('rejects archive digest tampering and missing candidate size',()=>{
  const bytes=archive();
  assert.throws(()=>extractPreviewZip(bytes,{...context(bytes),artifactSha256:'a'.repeat(64)}),/candidate_zip_hash/);
  const altered=archive([['preview.json',Buffer.from(JSON.stringify({candidateSha256:hash(tar),candidateBytes:0}))]]);
  assert.throws(()=>extractPreviewZip(altered,context(altered)),/candidate_digest/);
});
test('rejects missing, extra, duplicate, traversal, malformed, unsupported and forged members',()=>{
  for(const members of [
    [],
    [['preview.json',preview],['candidate.tar.gz',tar]],
    [['preview.json',preview],['candidate.tar.gz',tar],['extra',tar]],
    [['preview.json',preview],['preview.json',preview]],
    [['../preview.json',preview],['candidate.tar.gz',tar]],
    [['preview.json',preview,0xa0000000]],
  ]) {const bytes=archive(members);assert.throws(()=>extractPreviewZip(bytes,context(bytes)),/candidate_zip_/);}
  for(const alter of [
    b=>b.writeUInt16LE(8,8),
    b=>{b[30+'preview.json'.length]^=1;},
    b=>{const c=b.indexOf(Buffer.from([0x50,0x4b,0x01,0x02]));b.writeUInt32LE(1,c+24);},
    b=>{const c=b.indexOf(Buffer.from([0x50,0x4b,0x01,0x02]));b.writeUInt32LE(0xffffffff,c+20);},
  ]) {const bytes=archive();alter(bytes);assert.throws(()=>extractPreviewZip(bytes,context(bytes)),/candidate_zip_/);}
});
test('rejects invalid preview JSON and size mismatch',()=>{
  const bad=archive([['preview.json',Buffer.from('no')]]);
  assert.throws(()=>extractPreviewZip(bad,context(bad)),/candidate_preview/);
  const bytes=archive();assert.throws(()=>extractPreviewZip(bytes,{...context(bytes),artifactBytes:bytes.length+1}),/candidate_zip_size/);
});
test('rejects actual deflate bomb before any inflation',()=>{
  const compressed=require('node:zlib').deflateRawSync(Buffer.alloc(2*1024*1024));
  const bytes=archive([['preview.json',compressed]]);
  const central=bytes.indexOf(Buffer.from([0x50,0x4b,0x01,0x02]));
  bytes.writeUInt16LE(8,8);bytes.writeUInt16LE(8,central+10);
  bytes.writeUInt32LE(32,22);bytes.writeUInt32LE(32,central+24);
  assert.throws(()=>extractPreviewZip(bytes,context(bytes)),/candidate_zip_member/);
});
