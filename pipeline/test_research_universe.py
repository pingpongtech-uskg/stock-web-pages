from scripts.fetch_research_universe import parse_rankings, update_official_tracked_config


def test_parse_public_rank_table_keeps_rank_order_and_codes():
    document = """
    <h2>投信買超前 200 名</h2>
    <table><tr><th>排</th><th>代號</th><th>股名</th><th>買進</th><th>賣出</th><th>買超</th></tr>
      <tr><td>1</td><td>2892</td><td><a>第一金</a></td><td>9924</td><td>50</td><td>9874</td></tr>
      <tr><td>2</td><td>00980A</td><td>主動野村臺灣優選</td><td>394</td><td>0</td><td>394</td></tr>
    </table>
    <table><tr><td>投信賣超金額前 200 名</td></tr><tr><td>1</td><td>2330</td><td>台積電</td></tr></table>
    """
    rows = parse_rankings(document, limit=2)
    assert [row["code"] for row in rows] == ["2892", "00980A"]
    assert rows[0]["name"] == "第一金"


def test_official_config_persists_adjacent_window_and_top10_entry_status(tmp_path):
    snapshots = []
    for index in range(11):
        rows = [
            {"code": "A", "name": "甲", "market": "TWSE", "netShares": 100},
            {"code": "B", "name": "乙", "market": "TWSE", "netShares": 90},
        ]
        if index == 0:
            rows.append({"code": "NEW", "name": "新", "market": "TWSE", "netShares": 1000})
            rows.append({"code": "OLD", "name": "舊", "market": "TWSE", "netShares": 50})
        else:
            rows.append({"code": "OLD", "name": "舊", "market": "TWSE", "netShares": 1000})
        snapshots.append({"date": f"2026-09-{18 - index:02d}", "rows": rows})

    payload = update_official_tracked_config(snapshots, tmp_path / "tracked.json")

    assert payload["universe"]["label"] == "官方投信十日買超前100"
    assert payload["universe"]["marketDates"] == [f"2026-09-{18 - index:02d}" for index in range(10)]
    top10 = {row["code"]: row for row in payload["universe"]["top10"]}
    assert top10["NEW"]["entryStatus"] == "new"
    assert top10["OLD"]["entryStatus"] == "retained"
    assert payload["universe"]["previousRows"]
    assert len(payload["universe"]["dailyRows"]) == 10
    assert payload["universe"]["dailyRows"][0]["rows"]

