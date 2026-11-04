'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {zipFixture, hash} = require('./cache-fixture.cjs');
const {extractCandidateZip} = require('./peg-candidate-zip.cjs');
const tar=Buffer.from('frozen candidate');
const preview=Buffer.from(JSON.stringify({candidateSha256:hash(tar),stocks:[{code:'2330'}]}));
const archive=(members=[['preview.json',preview],['candidate.tar.gz',tar]])=>zipFixture(members);
const context=bytes=>({artifactBytes:bytes.length,artifactSha256:hash(bytes)});
test('authenticates ZIP, verifies candidate bytes, and returns parsed preview',()=>{
  const bytes=archive();
  assert.deepEqual(extractCandidateZip(bytes,context(bytes)), JSON.parse(preview));
  const described=archive([['candidate.tar.gz',tar,0,true],['preview.json',preview,0,'bare']]);
  assert.deepEqual(extractCandidateZip(described,context(described)),JSON.parse(preview));
});
test('rejects digest and candidate tampering',()=>{
  const bytes=archive();
  assert.throws(()=>extractCandidateZip(bytes,{...context(bytes),artifactSha256:'a'.repeat(64)}),/candidate_zip_hash/);
  const altered=archive([['preview.json',preview],['candidate.tar.gz',Buffer.from('different')]]);
  assert.throws(()=>extractCandidateZip(altered,context(altered)),/candidate_digest/);
});
test('rejects missing, extra, duplicate, traversal, malformed, unsupported and forged members',()=>{
  for(const members of [
    [['preview.json',preview]],
    [['preview.json',preview],['candidate.tar.gz',tar],['extra',tar]],
    [['preview.json',preview],['preview.json',preview]],
    [['../preview.json',preview],['candidate.tar.gz',tar]],
    [['preview.json',preview],['candidate.tar.gz',tar,0xa0000000]],
  ]) {const bytes=archive(members);assert.throws(()=>extractCandidateZip(bytes,context(bytes)),/candidate_zip_/);}
  for(const alter of [
    b=>b.writeUInt16LE(8,8),
    b=>{b[30+'preview.json'.length]^=1;},
    b=>{const c=b.indexOf(Buffer.from([0x50,0x4b,0x01,0x02]));b.writeUInt32LE(1,c+24);},
    b=>{const c=b.indexOf(Buffer.from([0x50,0x4b,0x01,0x02]));b.writeUInt32LE(0xffffffff,c+20);},
  ]) {const bytes=archive();alter(bytes);assert.throws(()=>extractCandidateZip(bytes,context(bytes)),/candidate_zip_/);}
});
test('rejects invalid preview JSON and size mismatch',()=>{
  const bad=archive([['preview.json',Buffer.from('no')],['candidate.tar.gz',tar]]);
  assert.throws(()=>extractCandidateZip(bad,context(bad)),/candidate_preview/);
  const bytes=archive();assert.throws(()=>extractCandidateZip(bytes,{...context(bytes),artifactBytes:bytes.length+1}),/candidate_zip_size/);
});
test('rejects actual deflate bomb before any inflation',()=>{
  const compressed=require('node:zlib').deflateRawSync(Buffer.alloc(2*1024*1024));
  const bytes=archive([['preview.json',compressed],['candidate.tar.gz',tar]]);
  const central=bytes.indexOf(Buffer.from([0x50,0x4b,0x01,0x02]));
  bytes.writeUInt16LE(8,8);bytes.writeUInt16LE(8,central+10);
  bytes.writeUInt32LE(32,22);bytes.writeUInt32LE(32,central+24);
  assert.throws(()=>extractCandidateZip(bytes,context(bytes)),/candidate_zip_member/);
});
