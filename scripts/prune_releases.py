#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,shutil
from pathlib import Path
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('--data-dir',type=Path,required=True); p.add_argument('--keep',type=int,default=3); p.add_argument('--max-bytes',type=int,default=250_000_000); a=p.parse_args(argv)
 data=a.data_dir; latest_path=data/'latest.json'
 if not latest_path.exists(): print('prune_blocked=latest missing'); return 1
 latest=json.loads(latest_path.read_text(encoding='utf-8')); current=str(latest.get('runId','')); releases=data/'releases'
 current_path=(releases/current).resolve()
 if not current or current_path.parent != releases.resolve() or not current_path.is_dir(): print('prune_blocked=current missing'); return 1
 dirs=sorted([p for p in releases.iterdir() if p.is_dir()],key=lambda p:p.stat().st_mtime,reverse=True)
 keep={current}
 for pth in dirs:
  if pth.name != current and len(keep) < a.keep: keep.add(pth.name)
 for pth in dirs:
  if pth.name not in keep: shutil.rmtree(pth)
 total=sum(p.stat().st_size for p in data.rglob('*') if p.is_file())
 if total>a.max_bytes: print(f'prune_blocked=size:{total}'); return 1
 print('prune_ok'); return 0
if __name__=='__main__': raise SystemExit(main())
