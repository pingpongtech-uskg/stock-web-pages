#!/usr/bin/env python3
"""Verify production latest/index/month JSON and cache headers against a candidate tree."""
from __future__ import annotations
import argparse, hashlib, json, re, urllib.request
from pathlib import Path
from urllib.parse import urlencode, urljoin
ROOT=Path(__file__).resolve().parents[1]
def get_json(base_url,path,cachebust):
 url=urljoin(base_url.rstrip('/')+'/',path.lstrip('/')); sep='&' if '?' in url else '?'
 req=urllib.request.Request(url+sep+urlencode({'cachebust':cachebust}),headers={'Accept':'application/json','Cache-Control':'no-cache','Pragma':'no-cache','User-Agent':'Mozilla/5.0 (compatible; stock-release-verifier/1.0)'})
 with urllib.request.urlopen(req,timeout=30) as resp:
  body=resp.read(); headers={k.lower():v for k,v in resp.headers.items()}
  if resp.status!=200: raise ValueError(f'http_status:{path}:{resp.status}')
 return json.loads(body),headers,body
def require_headers(path,headers,index):
 cache=headers.get('cache-control','').lower()
 if index:
  if not all(x in cache for x in ('no-cache','no-store','must-revalidate')): raise ValueError(f'cache_header_index:{path}:{cache}')
 else:
  if 'immutable' not in cache or 'public' not in cache: raise ValueError(f'cache_header_month:{path}:{cache}')
  m=re.search(r'max-age=(\d+)',cache)
  if not m or int(m.group(1))<31536000: raise ValueError(f'cache_age_month:{path}:{cache}')
def verify(base_url,expected_dir):
 data=Path(expected_dir); expected_latest=json.loads((data/'latest.json').read_text(encoding='utf-8')); expected_index=json.loads((data/'archive/v1/index.json').read_text(encoding='utf-8')); candidate=str(expected_latest.get('runId') or 'candidate')
 actual_export = None
 if (data/'screening-export.json').exists():
  actual_export, eh, eb = get_json(base_url, '/data/screening-export.json', candidate)
  expected_export_raw = (data/'screening-export.json').read_bytes()
  if eb != expected_export_raw: raise ValueError('screening_export_payload_mismatch')
  import sys
  if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
  from pipeline.screening_export import validate_export, hash_preimage
  if validate_export(actual_export): raise ValueError('screening_export_invalid')
  if hashlib.sha256(hash_preimage(eb)).hexdigest() != actual_export.get('payloadHash'): raise ValueError('screening_export_hash')
  require_headers('/data/screening-export.json', eh, True)
 actual_latest,lh,lb=get_json(base_url,'/data/latest.json',candidate); actual_index,ih,ib=get_json(base_url,'/data/archive/v1/index.json',candidate); require_headers('/data/latest.json',lh,True); require_headers('/data/archive/v1/index.json',ih,True)
 if actual_latest!=expected_latest: raise ValueError('latest_payload_mismatch')
 if actual_index!=expected_index: raise ValueError('history_index_payload_mismatch')
 months=expected_index.get('months') or []
 if not months: raise ValueError('history_index_empty')
 if actual_latest.get('marketDate')!=expected_index.get('latestMarketDate'): raise ValueError('latest_history_date_mismatch')
 latest_found=False; latest_meta=max(months,key=lambda x:str(x['month'])); latest_month_bytes=0
 for meta in months:
  month_path=str(meta['path'])
  if not re.fullmatch(r'/data/archive/v1/months/\d{4}-\d{2}\.[0-9a-f]{12}\.json',month_path): raise ValueError('history_month_filename')
  actual_month,mh,mb=get_json(base_url,month_path,candidate); require_headers(month_path,mh,False)
  expected_path=data/'archive/v1/months'/Path(month_path).name; expected_month=json.loads(expected_path.read_bytes())
  if actual_month!=expected_month: raise ValueError('history_month_payload_mismatch')
  digest=hashlib.sha256(mb).hexdigest()
  if digest!=str(meta['sha256']): raise ValueError('history_month_hash_mismatch')
  if len(mb)!=int(meta['bytes']): raise ValueError('history_month_bytes_mismatch')
  if Path(month_path).name.split('.')[1]!=digest[:12]: raise ValueError('history_month_filename_hash')
  if meta==latest_meta: latest_month_bytes=len(mb)
  for record in expected_month.get('records',[]):
   if record.get('marketDate')==expected_latest.get('marketDate'):
    latest_found=True
    if record.get('runId')!=expected_latest.get('runId'): raise ValueError('latest_history_run_mismatch')
    if actual_export and record.get('payloadHash') != actual_export.get('payloadHash'): raise ValueError('history_export_hash_mismatch')
   for ref in record.get('revisionRefs', []):
    if not re.fullmatch(r'/data/archive/v1/revisions/\d{4}-\d{2}-\d{2}\.[0-9a-f]{12}\.json',ref['path']): raise ValueError('history_revision_filename')
    saved, rh, rb = get_json(base_url, ref['path'], candidate)
    require_headers(ref['path'], rh, False)
    if hashlib.sha256(rb).hexdigest() != ref['sha256']: raise ValueError('history_revision_hash_mismatch')
    if rb!=(data/'archive/v1/revisions'/Path(ref['path']).name).read_bytes(): raise ValueError('history_revision_payload_mismatch')
 if not latest_found: raise ValueError('latest_history_record_missing')
 return {'valid':True,'baseUrl':base_url,'runId':expected_latest.get('runId'),'latestBytes':len(lb),'indexBytes':len(ib),'monthPath':latest_meta['path'],'monthBytes':latest_month_bytes,'monthsVerified':len(months)}
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('--base-url',required=True); p.add_argument('--expected-dir',type=Path,default=ROOT/'public/data'); a=p.parse_args(argv)
 try: result=verify(a.base_url,a.expected_dir)
 except Exception as exc: print(f'production_invalid={exc}'); return 1
 print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
