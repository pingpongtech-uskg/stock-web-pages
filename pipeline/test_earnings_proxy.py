from pipeline.earnings_proxy import derive_ltm_eps_proxy


def test_prefers_net_income_per_share_growth():
    rows = [
        {"year": 114, "quarter": 1, "revenue": 100, "grossProfit": 30, "operatingProfit": 10, "parentNetIncome": 5, "eps": 1.0},
        {"year": 114, "quarter": 2, "revenue": 100, "grossProfit": 30, "operatingProfit": 10, "parentNetIncome": 5, "eps": 1.0},
        {"year": 114, "quarter": 3, "revenue": 100, "grossProfit": 30, "operatingProfit": 10, "parentNetIncome": 5, "eps": 1.0},
        {"year": 114, "quarter": 4, "revenue": 100, "grossProfit": 30, "operatingProfit": 10, "parentNetIncome": 5, "eps": 1.0},
        {"year": 115, "quarter": 1, "revenue": 120, "grossProfit": 36, "operatingProfit": 12, "parentNetIncome": 6, "eps": 1.2},
        {"year": 115, "quarter": 2, "revenue": 120, "grossProfit": 36, "operatingProfit": 12, "parentNetIncome": 6, "eps": 1.2},
        {"year": 115, "quarter": 3, "revenue": 120, "grossProfit": 36, "operatingProfit": 12, "parentNetIncome": 6, "eps": 1.2},
        {"year": 115, "quarter": 4, "revenue": 120, "grossProfit": 36, "operatingProfit": 12, "parentNetIncome": 6, "eps": 1.2},
    ]
    result = derive_ltm_eps_proxy(rows, shares=5)
    assert result["method"] == "ltm_reported_eps"
    assert abs(result["growth"] - 0.2) < 1e-9
    assert result["current_eps"] == 4.8


def test_falls_back_to_gross_profit_per_share_when_net_income_missing():
    rows = [
        {"year": 114, "quarter": q, "revenue": 100, "grossProfit": 20, "operatingProfit": None, "parentNetIncome": None, "eps": None}
        for q in range(1, 5)
    ] + [
        {"year": 115, "quarter": q, "revenue": 120, "grossProfit": 30, "operatingProfit": None, "parentNetIncome": None, "eps": None}
        for q in range(1, 5)
    ]
    result = derive_ltm_eps_proxy(rows, shares=10)
    assert result["method"] == "ltm_gross_profit_eps_proxy"
    assert result["growth"] == 0.5
    assert result["current_eps"] == 12.0


def test_uses_revenue_and_margin_when_only_margin_is_available():
    rows = [
        {"year": 114, "quarter": q, "revenue": 100, "grossMargin": 0.2}
        for q in range(1, 5)
    ] + [
        {"year": 115, "quarter": q, "revenue": 120, "grossMargin": 0.25}
        for q in range(1, 5)
    ]
    result = derive_ltm_eps_proxy(rows, shares=10)
    assert result["method"] == "ltm_gross_profit_eps_proxy"
    assert result["growth"] == 0.5


def test_uses_revenue_proxy_without_calling_it_unknown():
    rows = [
        {"year": 114, "quarter": q, "revenue": 100}
        for q in range(1, 5)
    ] + [
        {"year": 115, "quarter": q, "revenue": 120}
        for q in range(1, 5)
    ]
    result = derive_ltm_eps_proxy(rows, shares=None)
    assert result["method"] == "ltm_revenue_proxy"
    assert abs(result["growth"] - 0.2) < 1e-9
