# Public Data Health Score Methodology

**Model version:** `public-data-health-v1`
**Formula version:** `public-data-health-v1`
**Scope:** independent public-data Taiwan stock model. It is not a promise to reproduce StatementDog or investment returns.

## Boundary

Production scorer reads normalized public facts only:

```text
TWSE OpenAPI → TPEx OpenAPI → MOPS → TDCC
FinMind → optional, budgeted free-tier fallback
 yfinance → optional, budgeted free-tier fallback
```

StatementDog is an external calibration label only. The scorer never fetches its page, API, cookie, session, or response.

## Status semantics

Every criterion returns exactly one of:

```text
pass          boolean condition is true and all inputs are valid
fail          boolean condition is false and all inputs are valid
unknown       required input is missing, future-announced, stale, conflicting,
              zero-denominator, or history is incomplete
not_applicable field is structurally not applicable, such as Piotroski tests
              for a financial-industry record
```

`unknown` is not `fail`. It is not removed from the category denominator. A
production publishing gate may exclude or block a row with unknown criteria,
but must retain the diagnostic result.

## Point-in-time rule

A financial fact is usable at `as_of` only when:

1. `announced_at <= as_of`;
2. its observation/market date is not later than `as_of`;
3. source, period, unit, statement scope, parser version, and content hash exist;
4. no conflicting value remains unresolved.

Daily market facts use their observed trading date. Missing announcement dates on
annual, quarterly, monthly, or dividend facts do not prove point-in-time safety
and therefore produce `unknown`.

## FCF convention

This model owns one explicit convention:

```text
FCF = CFO - positive Capital Expenditure
```

`CapEx` must be normalized as a positive cash-spending amount. `CFI` is not a
silent substitute. If CapEx is not available, FCF criteria are `unknown`.

## The 33 criteria

### 1. 轉機股 / turnaround — 3

| ID | Formula |
|---|---|
| `turnaround.pb_lt_3` | latest valid PB `< 3` |
| `turnaround.f_score_ge_8` | nine Piotroski item statuses complete and pass count `>= 8` |
| `turnaround.pb_lowest_top50` | valid PB ascending rank `<= 50` in complete TWSE+TPEx ordinary-share universe |

F-score items:

```text
ROA > 0
CFO > 0
CFO > Net Income
Long-term debt < prior year
Current ratio > prior year
Shares outstanding <= prior year
ROA > prior year
Gross margin > prior year
Asset turnover > prior year
```

`ROA = Net Income / average Total Assets`; `Current ratio = Current Assets /
Current Liabilities`. Zero denominators are `unknown`. Financial industry is
`not_applicable` for F-score.

### 2. 便宜股 / value — 6

```text
PE own-history lowest 20%       rank_min / n <= 0.20
PE universe 50%                 rank_min / n <= 0.50
PB own-history lowest 20%       rank_min / n <= 0.20
PB universe 50%                 rank_min / n <= 0.50
TTM cash yield > 6%             trailing cash dividend / as-of price * 100
5-year mean cash yield > 6%     mean(annual cash dividend / reference price * 100)
```

PE/PB valid population uses positive finite values. Own-history uses the
five-year date window; configured minimum observation floor is explicit. The
reference price is the last trading close on or before the target date.
Universe ranks require complete universe input. Ties use `rank_min`; top-N
ordering has deterministic company-code tie-break.

### 3. 成長股 / growth — 5

```text
latest three monthly revenue YoY values are all > 0
latest fiscal-quarter gross profit YoY > 0
latest fiscal-quarter operating income YoY > 0
latest fiscal-quarter pretax income YoY > 0
latest fiscal-quarter after-tax income YoY > 0
```

Quarter comparison is `fiscal_year/fiscal_quarter` matched to the same quarter
one year earlier. No positional index such as `dates[-5]`. Consolidated and
separate statements cannot be mixed.

### 4. 籌碼 / chip — 3

```text
major-holder ratio[t-2] < ratio[t-1] < ratio[t]
director/supervisor aggregate latest >= exact month 12 months earlier
TDCC shareholder_count[t-2] > shareholder_count[t-1] > shareholder_count[t]
```

A ratio calculated from an explicitly identified maximum holding tier is
`proxy=true`; it is not advertised as the exact major-holder definition.
TDCC weekly data is normalized to the latest available observation in each
calendar month.

### 5. 定存股 / dividend — 5

```text
trailing twelve-month cash yield > 6%
five-year mean annual cash yield > 6%
five consecutive attribution years have cash dividend
at least three of five annual payout ratios > 50%
five-year mean payout ratio > 50%
```

Only cash dividends are included by default. Special dividends are controlled
by config. `payout = annual cash dividend / annual EPS * 100`; EPS `<= 0` makes
the criterion `unknown`, never zero.

### 6. 績優股 / continuity — 5

```text
as_of > listing_date + 3 calendar years
FCF ROE(current) >= FCF ROE(prior year)
three-year mean FCF ROE ranks in highest 20%
sum of latest three annual operating income > 0
transparent PB+PE+yield composite rank <= 50
```

The historical `croic_*` IDs remain compatibility aliases for the current
criterion registry. This public model uses the user-approved definition:

```text
FCF ROE = FCF / average shareholders equity * 100
```

The composite is deliberately a `public_proxy`:

```text
(1 - PE percentile) + (1 - PB percentile) + yield percentile
```

`statementdog_exact=false` is always emitted for this composite.

### 7. 排除地雷股 / safety — 6

```text
FCF positive in >= 3 of five years
five-year mean FCF > 0
CFO / Net Income > 100% in >= 3 of five years
five-year mean CFO / Net Income > 100%
receivable days <= same fiscal quarter prior year
inventory days <= same fiscal quarter prior year
```

For CFO/net-income ratios, Net Income `<= 0` is `unknown`. Working-capital
formulas:

```text
receivable days = average(begin AR, end AR) / revenue * 365
inventory days  = average(begin inventory, end inventory) / COGS * 365
```

COGS is the explicit field when available. Otherwise the only permitted
same-statement derivation is `revenue - gross profit`, and the evidence records
that derivation. Revenue itself cannot substitute for COGS.

## Category output

Every company has fixed category totals `3/6/5/3/5/5/6` and counts:

```json
{
  "passed": 2,
  "failed": 1,
  "unknown": 0,
  "not_applicable": 0,
  "total": 3,
  "score": "2/3",
  "status": "pass"
}
```

Default category qualification threshold is `0.5`. Category status is
`unknown` when any criterion is unknown; otherwise it is pass when
`passed / active_criteria >= threshold`. `not_applicable` is excluded only from
that active-criteria qualification denominator; unknown is never excluded.

## Exact / proxy / unavailable

```text
official_exact  public source + frozen formula + complete point-in-time fields
public_proxy    transparent public derivation, explicitly marked proxy
unavailable     source/period/denominator/definition is not reliable enough
```

The model can produce its own seven-category numbers without claiming
StatementDog compatibility. Calibration labels are optional and isolated in
`scripts/grade_public_health_score.py`.
