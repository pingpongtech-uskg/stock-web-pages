#!/usr/bin/env python3
from __future__ import annotations
import argparse,re,sys
from pathlib import Path
import json
FORBIDDEN=("Chen Qiaohong","Qiaohong","影片版","老師本人","老師審核","teacher","video-style")
def _files_for_root(root: Path):
 if root.is_dir() and root.name == 'data' and (root / 'latest.json').exists():
  # Retired full releases remain immutable audit artifacts; only latest plus
  # the compact archive are rendered by the current product.
  latest = json.loads((root / 'latest.json').read_text(encoding='utf-8'))
  current = str(latest.get('runId') or '')
  selected = [root / 'latest.json', root / 'archive']
  if current:
   selected.append(root / 'releases' / current)
  return [f for p in selected if p.exists() for f in ([p] if p.is_file() else p.rglob('*'))]
 return [root] if root.is_file() else list(root.rglob('*'))

def scan(paths):
 hits=[]
 for root in paths:
  for f in _files_for_root(Path(root)):
   if not f.is_file() or f.suffix in {'.png','.jpg','.jpeg','.gif','.woff','.woff2'}: continue
   try: text=f.read_text(encoding='utf-8')
   except (UnicodeDecodeError,OSError): continue
   for i,line in enumerate(text.splitlines(),1):
    if any(term.lower() in line.lower() for term in FORBIDDEN): hits.append(f'{f}:{i}')
 return hits
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('--paths',nargs='+',required=True); a=p.parse_args(argv); hits=scan(a.paths)
 for hit in hits: print('neutral_copy_invalid='+hit)
 return 1 if hits else 0
if __name__=='__main__': raise SystemExit(main())
