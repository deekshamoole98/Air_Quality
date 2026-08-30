# Architecture

## Pipeline flow

```
EventBridge (scheduled rule, e.g. hourly)
        │
        ▼
  Lambda: lambda_handler.handler
        │
        ├── 1. ingestion/ingest.py
        │      OpenAQ v3 API ──► raw JSON ──► S3 (raw/date=YYYY-MM-DD/run_HHMMSS.json)
        │
        └── 2. triggers Glue job "air-quality-transform" (glue.start_job_run)
                     │
                     ▼
        glue_jobs/run_transform_glue.py (Glue Python Shell)
        imports transform/clean_transform.py ──► drop sentinel values,
        flag extreme outliers, dedupe, resolve city/country
                     │
                     ▼
        S3 curated Parquet (curated/date=YYYY-MM-DD/readings.parquet)
                     │
                     ▼
        Redshift Spectrum / Athena external table (schema: db/schema.sql)
                     │
                     ▼
        Metrics views (metrics/metrics.sql)
                     │
                     ▼
        QuickSight / Tableau / Power BI dashboard
```

See [`glue_setup_guide.md`](glue_setup_guide.md) for the full console
walkthrough of setting up the Glue job. `transform/clean_transform.py` can
still be called directly (in-process, no Glue) for local development — see
`python lambda_handler.py --local-transform` — the cleaning logic itself is
identical either way, only *where it executes* differs.

## Why the transform step runs in Glue, not the Lambda

The Lambda's execution time and memory are bounded, and `pandas`/`pyarrow`
add meaningful package size to the deployment. Moving cleaning into a Glue
Python Shell job means the Lambda stays a thin, fast trigger, and the
transform gets its own compute, its own IAM role, and its own logs — while
still calling the exact same tested function as local dev does.

## Why raw and curated are separate

Ingestion writes data as-is, including any bad values the API returns.
Cleaning logic lives entirely in the transform step. This means:
- If a cleaning rule is wrong or needs to change, historical raw data
  can be reprocessed without re-fetching from the API.
- Ingestion failures and transform failures can be debugged independently.

## Local development vs. deployed pipeline

`config.STORAGE_BACKEND` switches between `local` (writes to `./data/`,
no AWS account needed) and `s3` (writes to the configured bucket). This
lets the same code be developed and unit-tested entirely locally, then
deployed unchanged. `config.get_openaq_api_key()` is also lazy — the
transform side of the pipeline (including the Glue job) never needs an
OpenAQ API key in its environment at all, since it only ever reads
already-ingested raw data.

## EventBridge schedule (example)

```
Rule: air-quality-hourly-ingest
Schedule expression: rate(1 hour)
Target: lambda_handler.handler (Lambda function)
```

## IAM (minimum permissions for the Lambda execution role)

- `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` scoped to the pipeline's bucket/prefixes (needed for ingestion's raw output)
- `secretsmanager:GetSecretValue` (or `ssm:GetParameter`) scoped to the OpenAQ API key secret
- `glue:StartJobRun` scoped to the `air-quality-transform` job
- Standard `AWSLambdaBasicExecutionRole` for CloudWatch Logs

The Glue job itself runs under a *separate* role — see `glue_setup_guide.md` step 3.

## Known data quality issue this pipeline fixes

The original version of this project wrote every reading with
`city = NULL` and `country = "N/A"`, and included at least one
`-1.0 µg/m³` sentinel value from the API (OpenAQ's way of flagging a
missing/invalid reading, not a real measurement). Root cause: the
ingestion step only called `/parameters/{id}/latest`, which returns a
`locationsId` but not location metadata — a separate `/locations/{id}`
call is required to resolve city/country, and sentinel values were
never filtered before being stored. Both are fixed in this version:
metadata resolution happens in `ingestion/openaq_client.py`, and
filtering happens in `transform/clean_transform.py`.

## Sentinel values and extreme outliers

`config.SENTINEL_VALUES` (`-1`, `-999`, `9999`, `99999`) are dropped
outright — they mean "no valid reading," not a real measurement. This
matters beyond the negative case already mentioned above: a real
ingestion run turned up nineteen `9999.0` readings that the original
`value >= 0` filter missed entirely, since `9999` isn't negative.

Separately, values above `config.MAX_PLAUSIBLE_VALUE` (default 500 µg/m³)
are *flagged* via `is_extreme_outlier`, not dropped — a real extreme
pollution event is rare but possible, and what's actually behind most
readings this high (a miscalibrated sensor) is worth surfacing for
review rather than silently discarding. `metrics/metrics.sql`'s average
and trend views exclude flagged rows; `vw_flagged_outliers` lists them
for review.
