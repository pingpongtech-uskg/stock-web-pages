import json
from scripts.prune_releases import main

def test_prune_keeps_current_and_two_previous(tmp_path):
 d=tmp_path/'data'; r=d/'releases'; r.mkdir(parents=True)
 for n in ('a','b','c','d'): (r/n).mkdir(); (r/n/'x').write_text(n)
 (d/'latest.json').write_text(json.dumps({'runId':'a'}))
 assert main(['--data-dir',str(d),'--keep','3','--max-bytes','10000'])==0
 assert len(list(r.iterdir()))==3

def test_prune_guard_missing_current(tmp_path):
 d=tmp_path/'data'; d.mkdir(); (d/'latest.json').write_text(json.dumps({'runId':'missing'}))
 assert main(['--data-dir',str(d)])==1
