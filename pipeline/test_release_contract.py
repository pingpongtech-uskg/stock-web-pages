import pytest

from pipeline.release_contract import compute_funnel, is_common_stock_code


def valuation(*, proxy: bool = True, below: bool = True) -> dict[str, object]:
    if proxy:
        return {"growth_method": "three_month_revenue_proxy", "growth_method_label": "三月營收成長代理", "below_075": below}
    return {"growth_method": "ltm_reported_eps", "growth_method_label": "LTM 已公布 EPS 成長", "below_075": below}


def test_compute_funnel_counts_are_conserving():
    funnel = compute_funnel(
        universe=100,
        price_complete=7,
        instrument_excluded=4,
        valuations=[
            valuation(), valuation(), valuation(), valuation(),
            valuation(proxy=False),
            valuation(proxy=False, below=False),
        ],
        strategy_counts={"trust": 5, "growth": 5, "lowPosition": 2},
    )

    assert funnel["version"] == "funnel-v1"
    assert funnel["valuationComplete"] == 6
    assert funnel["pegCandidates"] == 5
    assert funnel["proxyValuations"] == 4
    assert funnel["formalValuations"] == 2
    assert funnel["strategyCandidates"]["lowPosition"] == 2
    assert funnel["instrumentExcluded"] == 4
    assert funnel["instrumentPolicy"] == "peg-strategies-exclude-non-common-codes-v1"


def test_compute_funnel_rejects_a_strategy_count_beyond_the_peg_pool():
    with pytest.raises(ValueError):
        compute_funnel(
            universe=100,
            price_complete=7,
            instrument_excluded=0,
            valuations=[valuation()],
            strategy_counts={"trust": 2},
        )


def test_common_stock_code_filter_separates_etf_and_etn_codes():
    assert is_common_stock_code("2330")
    assert is_common_stock_code("6488")
    assert is_common_stock_code("1504")
    assert not is_common_stock_code("0050")
    assert not is_common_stock_code("0056")
    assert not is_common_stock_code("009803")
    assert not is_common_stock_code("00980A")
    assert not is_common_stock_code("020000")
