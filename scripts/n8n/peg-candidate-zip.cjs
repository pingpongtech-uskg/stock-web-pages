'use strict';

// Authenticated GitHub artifact metadata bounds the ZIP; only stored entries are
// accepted, so untrusted data is never passed to an inflater in the n8n host.
const {createHash} = require('crypto');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const check = (ok, reason) => { if (!ok) throw Error('candidate_' + reason); };
const crcTable = Object.freeze(Array.from({length:256}, (_,index) => {
  let value = index;
  for (let bit=0; bit<8; bit++) value=(value>>>1)^((value&1)?0xedb88320:0);
  return value>>>0;
}));
function crc32(bytes) {
  let crc=0xffffffff;
  for (const byte of bytes) crc=(crc>>>8)^crcTable[(crc^byte)&255];
  return (crc^0xffffffff)>>>0;
}
function checkExtra(bytes,start,length) {
  for (let at=start; at<start+length;) {
    check(at+4<=start+length,'zip_extra');
    const type=bytes.readUInt16LE(at), size=bytes.readUInt16LE(at+2);
    check(type!==1 && at+4+size<=start+length,'zip_extra');
    at+=4+size;
  }
}
function extractCandidateZip(bytes, metadata) {
  check(Buffer.isBuffer(bytes) && bytes.length>=22 && bytes.length<=68*1024*1024 &&
    Number.isSafeInteger(metadata?.artifactBytes) && bytes.length===metadata.artifactBytes,'zip_size');
  check(/^[a-f0-9]{64}$/.test(metadata?.artifactSha256||'') && hash(bytes)===metadata.artifactSha256,'zip_hash');
  let end=-1;
  for (let index=bytes.length-22; index>=Math.max(0,bytes.length-65557); index--) {
    if (bytes.readUInt32LE(index)===0x06054b50 && index+22+bytes.readUInt16LE(index+20)===bytes.length) { end=index; break; }
  }
  check(end>=0 && bytes.readUInt16LE(end+4)===0 && bytes.readUInt16LE(end+6)===0,'zip_directory');
  const count=bytes.readUInt16LE(end+10), centralSize=bytes.readUInt32LE(end+12), centralOffset=bytes.readUInt32LE(end+16);
  check(count===2 && bytes.readUInt16LE(end+8)===count && centralOffset+centralSize===end,'zip_directory');
  let cursor=centralOffset; const members=[];
  for (let index=0; index<count; index++) {
    check(cursor+46<=end && bytes.readUInt32LE(cursor)===0x02014b50,'zip_directory');
    const crc=bytes.readUInt32LE(cursor+16), flags=bytes.readUInt16LE(cursor+8), method=bytes.readUInt16LE(cursor+10),
      compressed=bytes.readUInt32LE(cursor+20), expanded=bytes.readUInt32LE(cursor+24),
      nameSize=bytes.readUInt16LE(cursor+28), extra=bytes.readUInt16LE(cursor+30), comment=bytes.readUInt16LE(cursor+32),
      attributes=bytes.readUInt32LE(cursor+38), local=bytes.readUInt32LE(cursor+42);
    check(cursor+46+nameSize+extra+comment<=end && nameSize>0 && nameSize<=64,'zip_directory');
    const name=bytes.subarray(cursor+46,cursor+46+nameSize).toString('utf8');
    check(['preview.json','candidate.tar.gz'].includes(name) && !members.some(member=>member.name===name),'zip_member');
    check((flags&~0x808)===0 && method===0 && [0,0x8000].includes((attributes>>>16)&0xf000) && bytes.readUInt16LE(cursor+34)===0,'zip_member');
    const limit=name==='preview.json'?256*1024:64*1024*1024;
    check(compressed===expanded && expanded>0 && expanded<=limit,'zip_expansion');
    check(local+30<=centralOffset && bytes.readUInt32LE(local)===0x04034b50 && bytes.readUInt16LE(local+6)===flags && bytes.readUInt16LE(local+8)===method,'zip_local');
    const localName=bytes.readUInt16LE(local+26), localExtra=bytes.readUInt16LE(local+28);
    const dataOffset=local+30+localName+localExtra, dataEnd=dataOffset+compressed;
    check(dataEnd<=centralOffset && bytes.subarray(local+30,local+30+localName).toString('utf8')===name,'zip_local');
    checkExtra(bytes,cursor+46+nameSize,extra); checkExtra(bytes,local+30+localName,localExtra);
    const localCrc=bytes.readUInt32LE(local+14), localCompressed=bytes.readUInt32LE(local+18), localExpanded=bytes.readUInt32LE(local+22);
    let endOffset=dataEnd;
    if (flags&8) {
      check([0,crc].includes(localCrc) && [0,compressed].includes(localCompressed) && [0,expanded].includes(localExpanded) && dataEnd+12<=centralOffset,'zip_descriptor');
      const descriptor=dataEnd+(bytes.readUInt32LE(dataEnd)===0x08074b50?4:0);
      check(descriptor+12<=centralOffset && bytes.readUInt32LE(descriptor)===crc && bytes.readUInt32LE(descriptor+4)===compressed && bytes.readUInt32LE(descriptor+8)===expanded,'zip_descriptor');
      endOffset=descriptor+12;
    } else check(localCrc===crc && localCompressed===compressed && localExpanded===expanded,'zip_local');
    const data=bytes.subarray(dataOffset,dataEnd);
    check(crc32(data)===crc,'zip_crc');
    members.push({name,local,endOffset,data}); cursor+=46+nameSize+extra+comment;
  }
  check(cursor===end,'zip_directory');
  const ordered=[...members].sort((a,b)=>a.local-b.local);
  check(ordered[0].local===0 && ordered.every((entry,index)=>entry.endOffset===(ordered[index+1]?.local??centralOffset)),'zip_overlap');
  const files=Object.fromEntries(members.map(member=>[member.name,member.data]));
  let preview;
  try { preview=JSON.parse(files['preview.json'].toString('utf8')); } catch { throw Error('candidate_preview'); }
  check(preview && typeof preview==='object' && !Array.isArray(preview) && /^[a-f0-9]{64}$/.test(preview.candidateSha256||'') && hash(files['candidate.tar.gz'])===preview.candidateSha256,'digest');
  return preview;
}
module.exports = { extractCandidateZip };
