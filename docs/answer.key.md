# Seven Criteria Production Implementation Plan

**Goal:** Produce and display seven exact health-check groups for TWSE and TPEx ordinary shares using real, source-dated data, adjustable Z thresholds, and fail-closed results.

**Architecture:** Official-source adapters feed immutable dated snapshots. A pure Python engine evaluates 33 canonical criteria and emits criterion → group → stock results. Astro reads only the serialized verified payload; UI never invents or recalculates financial values.

**Scope defaults:** TWSE + TPEx ordinary shares; ETFs excluded; financial companies included unless source contract explicitly excludes them. Production sources are official TWSE, TPEx, TDCC, and MOPS. FinMind is calibration-only, not a silent production fallback.

## Execution order

1. Freeze registry and answer key.
2. Implement pure fail-closed engine and fixtures.
3. Implement allow-listed official adapters and dated snapshots.
4. Build a bounded real-data smoke for both markets.
5. Build the same-time TWSE+TPEx rank universe.
6. Run 500 distinct eligible calibration pairs against the approved reference; mismatches remain visible.
7. Serialize `criteria_groups` with provenance and integrate UI.
8. Run release gates, verify rollback artifact, then request deployment approval.

## Canonical groups

`safety` 6, `dividend` 5, `growth` 5, `value` 6, `turnaround` 3, `continuity` 5, `chip` 3. Total 33.

Every criterion returns `PASS`, `FAIL`, `UNKNOWN`, `BLOCKED`, `PARSE_ERROR`, or `STALE`, plus value, threshold, period, source date, source, parser version, and formula version. Missing data never becomes zero or a pass.

## Formula registry

- Safety: latest five FCF at least three positive; latest five FCF mean positive; latest five CFO/NI ratios at least three above 100%; their mean above 100%; receivable days not above prior period; inventory days not above prior period.
- Dividend: one-year yield above 6%; five-year average yield above 6%; five consecutive dividend years; at least three of latest five payout ratios above 50%; latest five payout ratio mean above 50%.
- Growth: latest three monthly revenue YoY values positive; latest-quarter gross profit, operating income, pretax income, and after-tax net income YoY positive.
- Value: current PE at or below five-year 20th percentile; PE below peer median; current PB at or below five-year 20th percentile; PB below peer median; one-year yield above 6%; five-year average yield above 6%.
- Turnaround: current PB below 3; annual Piotroski F-score at least 8 using nine fiscal-year-aligned tests; PB rank within the approved universe at most 50.
- Continuity: listed over 3 years; current FCF return at least prior-year FCF return; three-year FCF-return rank within top 20%; three-year operating income sum positive; PB+PE+yield composite rank within top 50.
- Chip: major-holder ownership increases for three consecutive months; latest director/supervisor/manager holding at least the twelve-month-ago value; total shareholder count decreases for three consecutive months.

## Z contract

`regression_z` is computed from a complete 882-trading-day positive close window using log-price OLS. Missing or invalid windows are UNKNOWN. UI presets are inclusive `Z <= 0`, `Z <= 1`, and `Z <= 2`; URL state is shareable. UI filtering does not recalculate Z.

## Calibration and release gates

- At least 500 distinct eligible TWSE+TPEx ordinary-share pairs.
- Exact `passed`, `count`, and normalized `pass_ratio` comparison for all seven groups.
- All candidate groups `status=ok`; otherwise calibration is BLOCKED.
- No look-ahead: source publication time must be no later than `as_of`.
- Historical chip and annual financial windows must be complete; no extrapolation.
- Full tests, compile, schema validation, provenance validation, security scan, and rollback artifact pass before production deployment.
