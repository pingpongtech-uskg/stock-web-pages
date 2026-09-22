#!/usr/bin/env python3
from __future__ import annotations
import argparse,re,sys
from pathlib import Path
FORBIDDEN=("Chen Qiaohong","Qiaohong","影片版","老師本人","老師審核","teacher","video-style")
def scan(paths):
 hits=[]
 for root in paths:
  p=Path(root)
  files=[p] if p.is_file() else [x for x in p.rglob('*') if x.is_file() and x.suffix not in {'.png','.jpg','.jpeg','.gif','.woff','.woff2'}]
  for f in files:
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
