from __future__ import annotations

import pytest

from scripts.collect_public_snapshot import _metric_row
from scripts.public_sources.mops import (
    build_historical_form,
    parse_mops_html,
    parse_number,
    select_unique_row,
)


FINANCE_HTML = """
<html><body>
<h2>合併現金流量表</h2>
<table>
<tr><th>民國114年第4季</th></tr>
<tr><th>單位：新台幣仟元</th></tr>
<tr><td>營業活動之淨現金流入（流出）</td><td>1,234,567</td><td>987,654</td></tr>
<tr><td>投資活動之淨現金流入（流出）</td><td>(321,000)</td><td>0</td></tr>
</table>
</body></html>
"""


INSIDER_HTML = """
<table>
<tr><th>資料年月:11507</th></tr>
<tr><th>職稱</th><th>姓名</th><th>選任時持股</th><th>目前持股</th></tr>
<tr><td>非獨立董事持股合計</td><td></td><td></td><td>123,000</td></tr>
<tr><td>大股東本人</td><td>甲</td><td>0</td><td>88,000</td></tr>
</table>
"""


def test_build_historical_form_uses_isnew_false_and_roc_period():
    form = build_historical_form("sii", "2330", year="114", season="04")
    assert form["TYPEK"] == "sii"
    assert form["co_id"] == "2330"
    assert form["isnew"] == "false"
    assert form["year"] == "114"
    assert form["season"] == "04"
    assert "month" not in form


def test_insider_form_uses_step_zero():
    form = build_historical_form("sii", "2330", year="115", month="07", endpoint="insider")
    assert form["step"] == "0"
    assert form["firstin"] == "true"


def test_parse_financial_html_keeps_period_unit_and_rows():
    document = parse_mops_html(
        FINANCE_HTML,
        code="2330",
        market="sii",
        requested_period="民國114年第4季",
    )
    assert document["period_match"] is True
    assert document["unit"] == "新台幣仟元"
    row = select_unique_row(document["rows"], "營業活動之淨現金流入（流出）")
    assert row["values"] == ["1,234,567", "987,654"]
    assert parse_number(row["values"][0]) == 1234567.0
    assert parse_number("(321,000)") == -321000.0


def test_parse_number_blank_and_malformed_are_missing():
    assert parse_number("") is None
    assert parse_number("-") is None
    assert parse_number("  ") is None
    with pytest.raises(ValueError, match="number"):
        parse_number("not-a-number")


def test_select_unique_row_rejects_duplicate_aggregate_label():
    rows = [
        {"label": "大股東本人", "values": ["1"]},
        {"label": "大股東本人", "values": ["2"]},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        select_unique_row(rows, "大股東本人")


def test_select_unique_row_skips_empty_financial_section_header():
    rows = [
        {"label": "基本每股盈餘", "values": ["", "", ""]},
        {"label": "基本每股盈餘", "values": ["66.26", "", "45.25"]},
    ]
    row = select_unique_row(rows, "基本每股盈餘")
    assert row["values"][0] == "66.26"


def test_metric_row_accepts_mops_eps_label_variant():
    document = {
        "period_match": True,
        "unit": "新台幣仟元",
        "rows": [{"label": "基本每股盈餘", "values": ["66.26", "", "45.25"]}],
    }
    label, value, reason = _metric_row(document, ("基本每股盈餘（元）", "基本每股盈餘"))
    assert label == "基本每股盈餘"
    assert value == 66.26
    assert reason is None


def test_parse_insider_html_supports_exact_period_marker():
    document = parse_mops_html(
        INSIDER_HTML,
        code="2330",
        market="sii",
        requested_period="資料年月:11507",
    )
    assert document["period_match"] is True
    row = select_unique_row(document["rows"], "非獨立董事持股合計")
    assert parse_number(row["values"][-1]) == 123000.0
