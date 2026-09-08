# Seven-Criteria Display Contract

Status: implementation contract, not calibration approval.

## Scope

The screener UI exposes seven health-check groups for every stock:

| Group ID | Label | Required criteria |
|---|---|---:|
| `safety` | 排除地雷股 | 6 |
| `dividend` | 定存股 | 5 |
| `growth` | 成長股 | 5 |
| `value` | 便宜股 | 6 |
| `turnaround` | 轉機股 | 3 |
| `continuity` | 續優股 | 5 |
| `chip` | 籌碼股 | 3 |

Total: 33 criteria.

## Result semantics

Each group is a complete result object:

```text
status: ok | missing | blocked | parse_error | stale
passed: integer | null
count: integer | null
pass_ratio: number | null       # 0..1, serialized once
result: pass | fail | unknown | blocked
threshold: number              # default 0.5
criteria: CriterionResult[]
source_date: YYYY-MM-DD | null
missing_reason: string | null
formula_version: string
```

`UNKNOWN`, missing, stale, parse errors, and blocked inputs never become a numeric zero and never pass silently.

A group can be labelled `PASS` only when `status=ok`, all required criteria are present, and `passed / count >= threshold`.

The overall stock result uses the seven group results. It is `PASS` only when all seven groups are `ok` and at least the selected group threshold is met. Otherwise it is `INCOMPLETE`, `BLOCKED`, or `FAIL` as appropriate.

## Adjustable parameters

- `z_max` is restricted to `0`, `1`, or `2` and means the card's `regression_z <= z_max`.
- `group_threshold` defaults to `0.5` and is restricted to the supported UI choices.
- Both values are URL state so a result view is shareable and reproducible.
- The frontend filters and displays server-generated criterion results; it does not invent formulas or recalculate financial data.

## Current repository gap

The current `screener_history.json` contains `g_score`, `l_score`, `cheap_score`, and `dividend_score`, but no verified seven-group result object. Until the seven-group runner and calibration are integrated, missing groups remain `UNKNOWN`; this contract does not promote legacy scores to exact StatementDog criteria.

## Provenance requirements

Every non-unknown criterion must carry its source, source date, retrieval time, parser version, and formula version. The UI shows source date and the reason for unknown values. Authenticated pages are not a production data source.
