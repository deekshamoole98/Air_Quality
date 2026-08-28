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
        └── 2. transform/clean_transform.py
               S3 raw JSON ──► filter invalid values, dedupe, resolve city/country
                            ──► S3 curated Parquet (curated/date=YYYY-MM-DD/readings.parquet)
                                        │
                                        ▼
                        Redshift Spectrum / Athena external table
                        (schema: db/schema.sql)
                                        │
                                        ▼
                        Metrics views (metrics/metrics.sql)
                                        │
                                        ▼
                        QuickSight / Tableau / Power BI dashboard
```

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
deployed unchanged.

## EventBridge schedule (example)

```
Rule: air-quality-hourly-ingest
Schedule expression: rate(1 hour)
Target: lambda_handler.handler (Lambda function)
```

## IAM (minimum permissions for the Lambda execution role)

- `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` scoped to the pipeline's bucket/prefixes
- `secretsmanager:GetSecretValue` (or `ssm:GetParameter`) scoped to the OpenAQ API key secret
- Standard `AWSLambdaBasicExecutionRole` for CloudWatch Logs

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
