from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_daily_freshness import freshness_errors


def write_release(tmp_path: Path, *, market_date: str = "2026-09-23", detail_date: str = "2026-09-23") -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    run_id = "run-1"
    detail_dir = data_dir / "releases" / run_id / "stocks"
    detail_dir.mkdir(parents=True)
    config_path = tmp_path / "tracked_symbols.json"
    config_path.write_text(json.dumps({"universe": {"marketDates": ["2026-09-23"]}}), encoding="utf-8")
    detail = {
        "code": "2330",
        "asOf": detail_date,
        "institutionDataAsOf": "2026-09-23",
        "institutionalDaily": [{"status": "pass"} for _ in range(10)],
        "regression": {"historyEnd": detail_date, "priceBasis": "adjusted"},
    }
    (detail_dir / "2330.json").write_text(json.dumps(detail), encoding="utf-8")
    release = {
        "runId": run_id,
        "marketDate": market_date,
        "marketIndicators": {"volumeMultiple00631L": {"marketDate": market_date}},
        "stocks": [{"code": "2330"}],
    }
    data_dir.mkdir(exist_ok=True)
    (data_dir / "latest.json").write_text(json.dumps(release), encoding="utf-8")
    return data_dir, config_path


def test_current_release_passes(tmp_path: Path) -> None:
    data_dir, config_path = write_release(tmp_path)
    assert freshness_errors(data_dir, config_path) == []


def test_old_market_date_is_rejected(tmp_path: Path) -> None:
    data_dir, config_path = write_release(tmp_path, market_date="2026-09-18", detail_date="2026-09-18")
    errors = freshness_errors(data_dir, config_path)
    assert any(error.startswith("release_market_date:") for error in errors)
    assert any(error.startswith("00631L_market_date:") for error in errors)
    assert any(error.startswith("price_date:") for error in errors)


def test_requested_date_independent_of_stale_official_config(tmp_path):
    data_dir, config_path = write_release(tmp_path)
    errors = freshness_errors(data_dir, config_path, '2026-09-24')
    assert 'official_market_date:2026-09-23!=2026-09-24' in errors
    assert any(error.startswith('release_market_date:') for error in errors)


def test_stale_flag_and_invalid_requested_date_rejected(tmp_path):
    data_dir, config_path = write_release(tmp_path)
    config_path.write_text(json.dumps({'universe': {'marketDates': ['2026-09-23'], 'stale': True}}))
    assert 'official_universe_stale' in freshness_errors(data_dir, config_path, '2026-09-23')
    assert freshness_errors(data_dir, config_path, '2026-9-23') == ['requested_market_date_invalid']


def test_missing_run_indicator_detail_and_incomplete_window_are_rejected(tmp_path):
    data_dir, config = write_release(tmp_path)
    path = data_dir/'latest.json'
    release = json.loads(path.read_bytes()); release.pop('marketIndicators'); path.write_text(json.dumps(release))
    detail = data_dir/'releases/run-1/stocks/2330.json'
    detail.write_text(json.dumps({'code':'2330','asOf':'2026-09-22','regression':None,
                                 'institutionDataAsOf':'2026-09-22','institutionalDaily':[]}))
    errors = freshness_errors(data_dir,config)
    assert '00631L_indicator_missing' in errors
    assert 'regression_missing:2330' in errors
    assert 'institution_window_incomplete:2330' in errors
    assert any(error.startswith('institution_date:') for error in errors)
    detail.unlink()
    assert 'detail_missing:2330' in freshness_errors(data_dir,config)
    release['runId']=''; path.write_text(json.dumps(release))
    assert 'release_run_id_missing' in freshness_errors(data_dir,config)


def test_invalid_config_dates_and_raw_regression_are_rejected(tmp_path):
    data_dir, config = write_release(tmp_path)
    config.write_text(json.dumps({'universe':{'marketDates':['bad',None]}}))
    assert freshness_errors(data_dir,config) == ['official_universe_market_date_missing']
    config.write_text(json.dumps({'universe':{'marketDates':['2026-09-23']}}))
    detail=data_dir/'releases/run-1/stocks/2330.json'
    value=json.loads(detail.read_bytes()); value['regression']={'historyEnd':'2026-09-22','priceBasis':'raw'}; detail.write_text(json.dumps(value))
    errors=freshness_errors(data_dir,config)
    assert 'regression_not_adjusted:2330' in errors
    assert any(error.startswith('regression_date:') for error in errors)


def test_freshness_cli_validates_independent_universe_and_full_release(tmp_path,monkeypatch):
    from scripts.verify_daily_freshness import main
    data_dir, config = write_release(tmp_path)
    base=['verify','--data-dir',str(data_dir),'--config',str(config)]
    monkeypatch.setattr('sys.argv',base+['--market-date','2026-09-23','--universe-only'])
    assert main() == 0
    monkeypatch.setattr('sys.argv',base+['--market-date','2026-09-24','--universe-only'])
    assert main() == 1
    monkeypatch.setattr('sys.argv',base+['--market-date','bad','--universe-only'])
    assert main() == 1
    monkeypatch.setattr('sys.argv',base+['--market-date','2026-09-23'])
    assert main() == 0
    (data_dir/'latest.json').write_text('broken')
    assert main() == 1


def test_publish_advisory_keeps_release_and_marks_only_affected_stock(tmp_path, monkeypatch, capsys):
    from scripts.verify_daily_freshness import main

    data_dir = tmp_path / 'data'
    run_id = 'daily-run'
    stocks_dir = data_dir / 'releases' / run_id / 'stocks'
    stocks_dir.mkdir(parents=True)
    config = tmp_path / 'tracked_symbols.json'
    config.write_text(json.dumps({'universe': {'marketDates': ['2026-10-07']}}), encoding='utf-8')

    def detail(code: str, as_of: str) -> dict:
        return {
            'code': code,
            'asOf': as_of,
            'institutionDataAsOf': as_of,
            'institutionalDaily': [{'date': as_of, 'status': 'pass'} for _ in range(10 if code == '2330' else 8)],
            'regression': {'historyEnd': as_of, 'priceBasis': 'adjusted'},
            'risks': [],
        }

    (stocks_dir / '6173.json').write_text(json.dumps(detail('6173', '2026-10-06')), encoding='utf-8')
    (stocks_dir / '2330.json').write_text(json.dumps(detail('2330', '2026-10-07')), encoding='utf-8')
    release = {
        'runId': run_id,
        'marketDate': '2026-10-07',
        'generatedAt': '2026-10-07T10:00:00Z',
        'freshness': 'current',
        'statusMessage': '已更新最新可得資料。',
        'marketIndicators': {'volumeMultiple00631L': {'marketDate': '2026-10-07'}},
        'stocks': [{'code': '6173', 'dataStatus': 'pass'}, {'code': '2330', 'dataStatus': 'pass'}],
        'rankings': {'trust': [{'code': '6173'}, {'code': '2330'}], 'growth': [], 'lowPosition': []},
    }
    latest = data_dir / 'latest.json'
    latest.write_text(json.dumps(release), encoding='utf-8')

    monkeypatch.setattr('sys.argv', [
        'verify', '--data-dir', str(data_dir), '--config', str(config),
        '--market-date', '2026-10-07', '--publish-advisory',
    ])

    assert main() == 0
    updated = json.loads(latest.read_text(encoding='utf-8'))
    affected = next(stock for stock in updated['stocks'] if stock['code'] == '6173')
    unaffected = next(stock for stock in updated['stocks'] if stock['code'] == '2330')
    affected_row = next(row for row in updated['rankings']['trust'] if row['code'] == '6173')
    unaffected_row = next(row for row in updated['rankings']['trust'] if row['code'] == '2330')
    affected_detail = json.loads((stocks_dir / '6173.json').read_text(encoding='utf-8'))

    assert updated['freshness'] == 'degraded'
    assert updated['dataQuality']['status'] == 'degraded'
    assert updated['dataQuality']['affectedStockCount'] == 1
    assert '6173' in updated['statusMessage']
    assert '2026-10-06' in updated['statusMessage']
    assert affected['dataFreshness'] == 'stale'
    assert affected_row['dataFreshness'] == 'stale'
    assert affected_detail['dataFreshness'] == 'stale'
    assert any('股價資料' in warning for warning in affected['freshnessWarnings'])
    assert unaffected.get('dataFreshness') != 'stale'
    assert unaffected_row.get('dataFreshness') != 'stale'
    assert '6173' in capsys.readouterr().out
