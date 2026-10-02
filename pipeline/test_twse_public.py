from pipeline.twse_public import _balance, _dividend, _income, _number, _revenue, _valuation


def test_number_handles_commas_and_blanks():
    assert _number("1,234.5") == 1234.5
    assert _number("") is None


def test_normalizers_keep_numeric_contract():
    assert _income({"營業收入": "10", "基本每股盈餘（元）": "2.5"})["revenue"] == 10
    assert _balance({"資產總計": "100", "負債總計": "40"})["equity"] is None
    assert _revenue({"資料年月": "202609", "營業收入-當月營收": "123"})["month"] == "2026-09"
    assert _dividend({"股東配發-盈餘分配之現金股利(元/股)": "3.0"})["cashPerShare"] == 3
    assert _valuation({"PEratio": "12", "PBratio": "1.2", "DividendYield": "4.5"})["pb"] == 1.2


def test_official_income_retains_ytd_basis_and_gregorian_period():
    result = _income({"年度": "115", "季別": "2", "出表日期": "1151001", "基本每股盈餘（元）": "5"})
    assert result["year"] == 2026
    assert result["quarter"] == 2
    assert result["periodType"] == "ytd"
    assert result["eps"] == 5
    assert result.get("publishedAt") is None


def test_dividend_sums_surplus_and_capital_cash_without_confirming_proposal():
    result = _dividend({"股利年度": "114", "股利所屬年(季)度": "114Q4",
                       "股東配發-盈餘分配之現金股利(元/股)": "1",
                       "股東配發-法定盈餘公積、資本公積之現金(元/股)": "2",
                       "董事會（擬議）股利分派日": "1150301", "出表日期": "1151001"})
    assert result["cashPerShare"] == 3
    assert result["confirmed"] is False


def test_bulk_official_feed_preserves_wanted_populations_and_endpoint_failures(monkeypatch):
    import pipeline.twse_public as public
    def endpoint(path, *, timeout):
        if path.endswith("BWIBBU_ALL"):
            return [{"Code": "2330", "Date": "1151001", "PEratio": "10", "PBratio": "2"},
                    {"Code": "9999", "Date": "1151001", "PEratio": "20"}]
        if path.endswith("t187ap05_L"):
            return [{"公司代號": "2330", "資料年月": "11508", "營業收入-當月營收": "100"}]
        if path.endswith("t187ap45_L"):
            raise TimeoutError("source outage")
        if "t187ap06" in path and path.endswith("_ci"):
            return [{"公司代號": "2330", "年度": "115", "季別": "2", "基本每股盈餘（元）": "5"}]
        if "t187ap07" in path:
            raise TimeoutError("financial endpoint unavailable")
        return []
    monkeypatch.setattr(public, "fetch_endpoint", endpoint)
    result = public.build_health_inputs(["2330", "1234"])
    assert set(result) == {"2330", "1234"}
    assert result["2330"]["valuationCurrent"]["date"] == "2026-10-01"
    assert result["2330"]["incomeQuarterly"][0]["periodType"] == "ytd"
    assert result["2330"]["monthlyRevenueOfficial"][0]["month"] == "2026-08"
    assert len(result["2330"]["valuationUniverse"]) == 2
    assert result["1234"]["incomeQuarterly"] == []
    assert "dividend" in result["2330"]["errors"]
    assert "balance" in result["2330"]["errors"]


def test_endpoint_reads_only_json_object_rows(monkeypatch):
    import io
    import pipeline.twse_public as public
    monkeypatch.setattr(public, "urlopen", lambda request, timeout: io.BytesIO(b'[{"Code":"2330"},null,4]'))
    assert public.fetch_endpoint("exchangeReport/BWIBBU_ALL") == [{"Code": "2330"}]
