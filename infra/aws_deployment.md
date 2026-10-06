# AWS deployment (what actually ran)

```
Lambda (ingest) -> S3 raw JSON -> Glue Python Shell job (clean) -> S3 curated Parquet
                                                         -> Athena (table + views) -> QuickSight
```

Region `us-east-1` throughout. Replace `YOUR_BUCKET_NAME` with your bucket name (S3 names are
globally unique, so something like `yourname-air-quality`). IAM policies are in `infra/iam/`.
Everything below was done in the AWS console.

## 1. S3 bucket
Create a bucket with Block Public Access left on. The pipeline creates its own `raw/` and
`curated/` prefixes. Create `glue-deps/` and `glue-scripts/` folders yourself.

## 2. Lambda (ingestion)
1. IAM role: trust policy `infra/iam/lambda_trust_policy.json`, managed policy `AWSLambdaBasicExecutionRole`,
   inline policy `infra/iam/lambda_permissions_policy.json`.
2. Build the zip: put `lambda_handler.py`, `config.py`, `ingestion/`, `storage/` in a folder, then
   `pip install requests --target <folder>` (without `--no-deps`, since `requests` needs its dependencies).
   Zip the folder's *contents* so the `.py` files sit at the zip root. `boto3` is already in the Lambda runtime.
3. Create the function: Python 3.12, handler `lambda_handler.handler`, timeout 5 min, memory 256 MB.
4. Environment variables: `STORAGE_BACKEND=s3`, `S3_BUCKET`, `GLUE_JOB_NAME=air-quality-transform`,
   `OPENAQ_API_KEY`, `OPENAQ_PAGE_LIMIT=50`. Don't attach the function to a VPC.

## 3. Glue transform job
1. IAM role: trust policy `infra/iam/glue_trust_policy.json`, managed policy `AWSGlueServiceRole`,
   inline policy `infra/iam/glue_s3_access_policy.json`.
2. Upload `glue_jobs/flat/config.py`, `clean_transform.py`, `storage_helpers.py` **individually** (not zipped)
   to `s3://YOUR_BUCKET_NAME/glue-deps/`.
3. Glue console -> ETL jobs -> **Script editor** -> engine **Python Shell**. Name it `air-quality-transform`.
4. **Script** tab: paste `glue_jobs/flat/run_transform_glue.py`.
5. **Job details**: your Glue role, Python 3.9, and Python library path set to the three files, comma-separated, no spaces:
   `s3://YOUR_BUCKET_NAME/glue-deps/config.py,s3://YOUR_BUCKET_NAME/glue-deps/clean_transform.py,s3://YOUR_BUCKET_NAME/glue-deps/storage_helpers.py`
6. Job parameter: `--BUCKET` = your bucket name.

## 4. Test the chain
Lambda -> Test. The response should include `raw_location` and `glue_job_run_id`. Then check that Glue's
Runs tab shows **Succeeded** with `Done. N curated rows written`, and that `curated/date=.../readings.parquet` exists.

## 5. Athena
1. Set a query result location (e.g. `s3://YOUR_BUCKET_NAME/athena-results/`). If the console sends you to SageMaker Unified Studio, choose the classic Athena query editor.
2. Run `db/athena_schema.sql` (after replacing the bucket name), then `MSCK REPAIR TABLE air_quality_curated;`.
3. Run the three views in `metrics/metrics_athena.sql`, one at a time.

## 6. QuickSight
Grant it access to Athena and your regular S3 bucket (not "S3 Tables"). Create an Athena data source, then one
dataset per view, imported to SPICE. SPICE is a copy, so refresh it after changing a view or loading new data.
Screenshots of the result are in `docs/`.

**Cost:** QuickSight bills per user and has no free tier or pause. Deleting the subscription is the only way to stop
charges, and it permanently deletes dashboards. Everything else here costs cents at this data size.

## Gotchas (each of these cost real debugging time)

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError` for your own modules in Glue | Python Shell jobs can't load a `.zip` of packages through the library path, whatever its layout. Use `.py` files listed individually, or a `.whl`/`.egg`. |
| Job "succeeds" but logs end after `Starting script execution` | The job was running a different script. The Script path field is a **folder**, and the file Glue runs is named after the job. Edit the script in the console's Script tab instead. |
| `usage: ... the following arguments are required` | `getResolvedOptions` exits the process (SystemExit) when an argument is missing; `except Exception` doesn't catch that. Check `"--NAME" in sys.argv` first. |
| No error in logs | Glue splits stdout and stderr into `/aws-glue/python-jobs/output` and `/error`. Print with `flush=True` and print the traceback to stdout. |
| 0 curated rows from non-empty raw data | Real OpenAQ responses use `datetime.utc` and `locationsId`, and have no `parameter` field. The cleaner assumed other names and silently dropped every row. |
| Bad values in the data | Sentinels appear on both sides (`-1`, `-9999`, `9999`). Dropped outright. Implausibly high values are flagged, not dropped. |
| Lambda times out | One metadata API call per station. `OPENAQ_PAGE_LIMIT=1000` is too slow; 50 worked. |
| Lambda `Unable to import module` | Bundle `requests` *with* its dependencies. `config.py` treats `python-dotenv` as optional. |
| Lambda `HandlerNotFound` | Handler is `lambda_handler.handler` (file name, then function name). |
| 401 vs 429 from OpenAQ | 401 is a wrong or stale API key. 429 is rate limiting; honor `Retry-After`. |
| Zips from Windows `Compress-Archive` | They store backslash paths. Build zips with Python's `zipfile` or another tool. |
| Athena shows 0 rows | New `date=` folders need `MSCK REPAIR TABLE air_quality_curated;`. |
| Charts look stale or too old | `/latest` returns each station's most recent reading, often months old, so the views keep the last 7 days. QuickSight's SPICE copy needs a manual refresh. |
