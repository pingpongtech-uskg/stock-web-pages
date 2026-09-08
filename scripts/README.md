# Public health score scripts

All commands run from the repository root. They use official normalized input
only; they do not fetch StatementDog.

## Daily score

```bash
python3 scripts/run_public_health_score.py \
  --date YYYY-MM-DD \
  --input data/raw/taiwan-stocks \
  --output data/derived/public-health-score/YYYY-MM-DD
```

Optional controls:

```bash
--threshold safety=0.5
--threshold value=0.67
--include-special-dividends
--z-max 0
--min-history-observations 20
```

The input directory must contain a hash-verifiable `manifest.json` with
`status=complete`. Input files contain canonical company records or JSONL
records. The runner passes the complete loaded universe to every company score;
it never computes a rank on a one-company subset.

## Output files

```text
predictions.jsonl       one seven-category score per company
score_summary.json      aggregate category counts and scores
errors.jsonl            sanitized input/conflict/score diagnostics
run_manifest.json       run id, hashes, versions, counts, exit code
```

`unknown_count` counts unknown criteria. Unknown is visible in predictions and
never changed into fail. Nonzero exit means input error, unresolved data
conflict, or a company scoring exception.

## External calibration

```bash
python3 scripts/grade_public_health_score.py \
  --predictions data/derived/public-health-score/YYYY-MM-DD/predictions.jsonl \
  --gold calibration/external-gold.jsonl \
  --out calibration/reports/YYYY-MM-DD.json
```

Gold is read only by the grader. The scorer never imports or receives gold
labels. Grader reports exact category agreement, pass-count error, normalized
MAE, ordinal agreement, unknown/proxy rates, criterion confusion metrics when
individual labels exist, and deterministic bootstrap intervals.

## Exit and release rule

A successful script run proves execution, not model accuracy. Release still
requires offline tests, full eligible-universe dry-run, field completeness,
formula review, calibration, build validation, and a fail-closed publish gate.
Do not auto-enable cron from these scripts.
