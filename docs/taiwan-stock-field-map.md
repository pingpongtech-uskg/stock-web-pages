# Taiwan Stock Normalized Field Map

Model/formula version: `public-data-health-v1`

## Identity and point-in-time

| Normalized field | Required shape | Primary source | Period | Missing behavior |
|---|---|---|---|---|
| `company_code` | four-to-six digit string; keep leading zeros | TWSE/TPEx company master | current | record error |
| `company_name` | string | TWSE/TPEx company master | current | record error |
| `market` | `TWSE` or `TPEx` | company master | current | record error |
| `listing_date` | ISO date | company master | current | continuity F1 unknown |
| `statement_scope` | consolidated/separate | MOPS/TWSE/TPEx | each statement | mixed scope blocked |
| `announced_at` | ISO date/time | source publication metadata | each fact | financial fact unknown when absent |
| `content_sha256` | `sha256:<64 hex>` | raw snapshot manifest | each source response | lineage error |

## Annual financial facts

All annual facts use `period=YYYY-FY`, `period_type=annual`, and the same
statement scope.

| Field | Source | Formula use |
|---|---|---|
| `cfo` | MOPS cash flow | FCF, CFO/NI, F-score |
| `capex` | MOPS cash flow / normalized CapEx line | FCF = CFO - CapEx |
| `net_income` | MOPS income | CFO/NI, ROA |
| `eps` | MOPS income | payout |
| `revenue` | MOPS income | margins, asset turnover |
| `gross_profit` | MOPS income | gross margin |
| `operating_income` | MOPS income | growth, continuity |
| `total_assets` | MOPS balance | ROA/asset turnover |
| `current_assets` | MOPS balance | current ratio |
| `current_liabilities` | MOPS balance | current ratio |
| `long_term_debt` | MOPS balance | F-score; never total-liabilities proxy |
| `shares` | MOPS/company master | F-score new-share test |
| `equity` | MOPS balance | FCF ROE |
| `receivables` | MOPS balance | working-capital days |
| `inventory` | MOPS balance | working-capital days |

A five-year criterion needs five complete fiscal years. F-score ROA/asset
turnover comparisons need an additional prior asset observation for the
prior-year average.

## Quarterly facts

Use `period=YYYY-QN`, `period_type=quarterly`:

```text
gross_profit
operating_income
pretax_income
after_tax_income
revenue
receivables_begin / receivables_end
inventory_begin / inventory_end
cost_of_goods_sold
```

The current quarter is selected by fiscal period, then paired with
`previous_year_period(current_period)`. Positional list indexes are forbidden.

## Monthly facts

Use `period=YYYY-MM`, `period_type=monthly`:

```text
monthly_revenue
prior_year_same_month_revenue
major_holder_ratio                 # direct or explicit proxy
major_holder_shares
major_holder_denominator
director_supervisor_aggregate_holdings
shareholder_count
```

Three-month criteria need three chronological periods. The twelve-month
董監 comparison needs the exact period shifted by `-12` months.

## Market and valuation facts

Use daily observed trading dates:

```text
price
pe
pb
dividend_yield
```

Only `price`, `pe`, and `pb` are used for the current market snapshot. Yield
criteria recompute cash yield from dividends and price rather than trusting a
provider summary yield.

Five-year PE/PB history requires dated positive finite daily observations.
Current universe ranks require one same-date value per eligible ordinary share.

## Dividends

Each normalized dividend record contains:

```json
{
  "attribution_year": 2024,
  "cash_per_share": 1.0,
  "ex_date": "2025-02-20",
  "announced_at": "2025-02-15",
  "special": false,
  "source_id": "mops.dividend",
  "content_sha256": "sha256:<64 hex>"
}
```

Attribution year controls five-year continuity and payout. Announcement year
must not replace attribution year. Special dividend inclusion is configuration.

## Status and conflicts

A normalized fact with missing value is `unknown`. Two same-field/same-period
values from different providers are preserved and emitted as `data_conflict`;
the scorer will not select one silently.
