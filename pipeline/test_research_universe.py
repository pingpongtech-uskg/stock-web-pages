from scripts.fetch_research_universe import parse_rankings


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

