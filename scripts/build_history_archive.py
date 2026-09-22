#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from collections import defaultdict
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from pipeline.history_archive import project_release_to_history, merge_month, prune_to_retention, write_archive_atomic

def main(argv=None):
 import argparse
 p=argparse.ArgumentParser(); p.add_argument('--data-dir',type=Path,default=ROOT/'public/data'); p.add_argument('--as-of'); p.add_argument('--retention-days',type=int,default=366); p.add_argument('--check-only',action='store_true'); a=p.parse_args(argv)
 latest=json.loads((a.data_dir/'latest.json').read_text(encoding='utf-8'))
 records=[]
 for candidate in [latest]:
  if candidate.get('marketDate'): records.append(project_release_to_history(candidate))
 if not records: print('archive_blocked=missing marketDate'); return 2
 months=defaultdict(list)
 archive=a.data_dir/'archive/v1'
 if archive.exists() and (archive/'index.json').exists():
  for meta in json.loads((archive/'index.json').read_text(encoding='utf-8')).get('months',[]):
   path=archive.parent.parent / str(meta['path']).removeprefix('/data/')
   if path.exists():
    for row in json.loads(path.read_bytes()).get('records',[]): months[meta['month']]=merge_month(months[meta['month']],row)
 for record in records: months[record['marketDate'][:7]]=merge_month(months[record['marketDate'][:7]],record)
 end=date.fromisoformat(a.as_of) if a.as_of else date.today(); months=prune_to_retention(months,end,a.retention_days)
 if a.check_only: print('archive_check_ok'); return 0
 write_archive_atomic(a.data_dir/'.history-staging',archive,months,latest.get('generatedAt')); print('archive_built'); return 0
if __name__=='__main__': raise SystemExit(main())
