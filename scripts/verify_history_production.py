#!/usr/bin/env python3
"""Verify production latest/index/month JSON and cache headers against a candidate tree."""
from __future__ import annotations
import argparse, hashlib, json, re, urllib.request
from pathlib import Path
from urllib.parse import urlencode, urljoin
ROOT=Path(__file__).resolve().parents[1]
def get_json(base_url,path,cachebust):
 url=urljoin(base_url.rstrip('/')+'/',path.lstrip('/')); sep='&' if '?' in url else '?'
 req=urllib.request.Request(url+sep+urlencode({'cachebust':cachebust}),headers={'Accept':'application/json','Cache-Control':'no-cache','Pragma':'no-cache'})
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
 actual_latest,lh,lb=get_json(base_url,'/data/latest.json',candidate); actual_index,ih,ib=get_json(base_url,'/data/archive/v1/index.json',candidate); require_headers('/data/latest.json',lh,True); require_headers('/data/archive/v1/index.json',ih,True)
 if actual_latest!=expected_latest: raise ValueError('latest_payload_mismatch')
 if actual_index!=expected_index: raise ValueError('history_index_payload_mismatch')
 months=expected_index.get('months') or []
 if not months: raise ValueError('history_index_empty')
 meta=max(months,key=lambda x:str(x['month'])); month_path=str(meta['path']); actual_month,mh,mb=get_json(base_url,month_path,candidate); require_headers(month_path,mh,False)
 expected_path=data/'archive/v1/months'/Path(month_path).name; expected_month=json.loads(expected_path.read_bytes())
 if actual_month!=expected_month: raise ValueError('history_month_payload_mismatch')
 digest=hashlib.sha256(mb).hexdigest()
 if digest!=str(meta['sha256']): raise ValueError('history_month_hash_mismatch')
 if len(mb)!=int(meta['bytes']): raise ValueError('history_month_bytes_mismatch')
 if not re.fullmatch(r'\d{4}-\d{2}\.[0-9a-f]{12}\.json',Path(month_path).name): raise ValueError('history_month_filename')
 if Path(month_path).name.split('.')[1]!=digest[:12]: raise ValueError('history_month_filename_hash')
 if actual_latest.get('marketDate')!=expected_index.get('latestMarketDate'): raise ValueError('latest_history_date_mismatch')
 dates=[r.get('marketDate') for r in expected_month.get('records',[])]
 if expected_latest.get('marketDate') in dates:
  record=next(r for r in expected_month['records'] if r.get('marketDate')==expected_latest['marketDate'])
  if record.get('runId')!=expected_latest.get('runId'): raise ValueError('latest_history_run_mismatch')
 return {'valid':True,'baseUrl':base_url,'runId':expected_latest.get('runId'),'latestBytes':len(lb),'indexBytes':len(ib),'monthPath':month_path,'monthBytes':len(mb)}
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('--base-url',required=True); p.add_argument('--expected-dir',type=Path,default=ROOT/'public/data'); a=p.parse_args(argv)
 try: result=verify(a.base_url,a.expected_dir)
 except Exception as exc: print(f'production_invalid={exc}'); return 1
 print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
