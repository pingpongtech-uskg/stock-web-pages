import io
import json
from scripts.build_trading_calendar import main
from pipeline.test_trading_calendar import ROWS


def test_calendar_cli_writes_open_day_and_never_overwrites_on_closed_or_wrong_year(tmp_path,monkeypatch):
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen',lambda *args,**kwargs: io.StringIO(json.dumps(ROWS)))
    output=tmp_path/'calendar.json'
    assert main(['--market-date','2026-10-02','--output',str(output)])==0
    original=output.read_bytes()
    value=json.loads(original)
    assert value['sourceUrl']=='https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule'
    assert '2026-10-09' in value['closedDates']
    assert main(['--market-date','2026-10-09','--output',str(output)])==1
    assert output.read_bytes()==original
    assert main(['--market-date','2027-01-04','--output',str(output)])==1
    assert output.read_bytes()==original


def test_calendar_cli_rejects_non_json_response(tmp_path,monkeypatch):
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen',lambda *args,**kwargs: io.StringIO('<html>upstream error</html>'))
    output=tmp_path/'calendar.json'
    assert main(['--market-date','2026-10-02','--output',str(output)])==1
    assert not output.exists()
