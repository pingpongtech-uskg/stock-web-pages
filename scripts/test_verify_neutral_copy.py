from scripts.verify_neutral_copy import scan

def test_neutral_scanner_rejects_attribution(tmp_path):
 p=tmp_path/'x.ts'; p.write_text('影片版總報酬本益比',encoding='utf-8')
 assert scan([tmp_path])
