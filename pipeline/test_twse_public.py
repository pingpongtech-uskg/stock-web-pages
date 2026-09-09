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
