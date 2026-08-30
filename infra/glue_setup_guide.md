# Setting Up the Glue Transform Job

Moves data cleaning out of the Lambda and into a real AWS Glue job, so the
pipeline looks like:

```
EventBridge (schedule)
        │
        ▼
  Lambda: lambda_handler.handler
        │
        └── ingestion/ingest.py → OpenAQ API → S3 (raw)
        │
        └── triggers Glue job "air-quality-transform"
                     │
                     ▼
        glue_jobs/run_transform_glue.py
        (imports & runs transform/clean_transform.py — same tested
         cleaning logic: sentinel filtering, outlier flagging, dedup, city/country)
                     │
                     ▼
        S3 (curated, Parquet) → Redshift/Athena → metrics views → dashboard
```

## 1. Package the code as a Glue dependency

Glue Python Shell jobs need your modules available via `--extra-py-files`.
Zip up what the transform step actually imports — not the whole repo, just
`config.py`, `transform/`, and `storage/`:

```bash
cd air_quality_pipeline
zip -r glue_dependencies.zip config.py transform/ storage/
aws s3 cp glue_dependencies.zip s3://your-air-quality-bucket/glue-deps/glue_dependencies.zip
```

Re-run this and re-upload any time you change `transform/clean_transform.py`
or `config.py` — Glue reads whatever's at that S3 path when the job starts.

## 2. Upload the job script itself

```bash
aws s3 cp glue_jobs/run_transform_glue.py s3://your-air-quality-bucket/glue-scripts/run_transform_glue.py
```

## 3. Create the IAM role for the Glue job

A role separate from the Lambda's, with:
- `AWSGlueServiceRole` (AWS managed policy — standard Glue permissions)
- `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` scoped to your bucket
  (both the data prefixes and the `glue-deps`/`glue-scripts` prefixes)

## 4. Create the Glue job (console)

1. AWS Glue console → **ETL jobs** → **Create job**
2. Choose **Python Shell script editor** — this is a Python Shell job, not Spark
3. **Job details**:
   - Name: `air-quality-transform`
   - IAM role: the one from step 3
   - Python version: 3.9
   - Script path: `s3://your-air-quality-bucket/glue-scripts/run_transform_glue.py`
   - Python library path: `s3://your-air-quality-bucket/glue-deps/glue_dependencies.zip`
4. Under Advanced properties → **Job parameters**, add `--BUCKET` = `your-air-quality-bucket`
   as a default (the Lambda still passes it explicitly on every run — this
   just lets you test-run the job manually from the console too)
5. Save

## 5. Test-run it manually first

Before wiring up the Lambda trigger, run it once by hand: **Actions → Run job**,
with job parameters:
- `--BUCKET` = `your-air-quality-bucket`
- `--PROCESS_DATE` = a date that already has raw data in S3 (run ingestion
  at least once first)

Check the **Runs** tab for status and CloudWatch Logs for the printed row count.

## 6. Point the Lambda at it

Lambda environment variables:
```
GLUE_JOB_NAME=air-quality-transform
S3_BUCKET=your-air-quality-bucket
```

The Lambda's execution role also needs `glue:StartJobRun` permission scoped
to this job, in addition to its existing S3/Secrets Manager permissions.

## 7. Local development without touching Glue at all

```bash
python lambda_handler.py --local-transform
```

Runs ingestion and the same cleaning function in-process (works fine with
`STORAGE_BACKEND=local`) — useful for checking a logic change before
re-zipping and uploading to S3 for Glue to pick up.

## Why bother with the extra setup

The cleaning logic isn't duplicated between environments — Glue imports and
calls the exact `run_transform_for_date()` that's covered by
`tests/test_clean_transform.py`. The only genuinely new code is the ~40-line
wrapper in `glue_jobs/run_transform_glue.py` that resolves job parameters
and sets env vars before importing it.
