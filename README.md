# Air Quality Reporting Pipeline

End-to-end PM2.5 monitoring pipeline built on AWS: pulls air quality readings from the OpenAQ API, cleans and validates them, lands curated Parquet in S3, and serves metric views to a QuickSight dashboard. Fully deployed and run in a live AWS account.

**Stack:** Python · AWS Lambda · S3 · Glue · Athena · QuickSight · SQL

---

## What it does

Tracks which cities are consistently exceeding WHO's PM2.5 air quality guideline (15 µg/m³) and whether they're trending better or worse week over week. A one-off query answers that once; this pipeline answers it every week without redoing the work.

**Metrics produced:**
- Daily average PM2.5 by city (last 7 days, outliers excluded)
- % of readings exceeding the WHO 24-hour guideline per city
- Week-over-week PM2.5 change by city
- Flagged extreme outliers surfaced for manual review

Dashboard exports: [overview](docs/dashboard_overview.pdf) · [week-over-week trend](docs/dashboard_week_over_week.pdf)

---

## Architecture

```
EventBridge (scheduled rule)
        │
        ▼
  Lambda (lambda_handler.py)
        │
        ├── ingestion/ingest.py
        │     OpenAQ v3 API → raw JSON → S3 (raw/date=YYYY-MM-DD/run_HHMMSS.json)
        │
        └── triggers Glue Python Shell job (glue.start_job_run)
                    │
                    ▼
        glue_jobs/flat/run_transform_glue.py
              clean_transform.py: drop sentinel values, flag outliers, dedupe, resolve city/country
                    │
                    ▼
        S3 curated Parquet (curated/date=YYYY-MM-DD/readings.parquet)
                    │
                    ▼
        Athena external table + metric views (metrics/metrics_athena.sql)
                    │
                    ▼
        QuickSight dashboard
```

The transform runs in its own Glue job rather than inside the Lambda — keeps Lambda thin, gives cleaning its own compute, logs, and IAM role. Full design notes: [`infra/architecture.md`](infra/architecture.md).

---

## Repository layout

| Path | Purpose |
|---|---|
| `config.py` | All config via env vars — nothing hardcoded |
| `ingestion/` | OpenAQ API client, lands raw JSON |
| `transform/` | Cleaning, deduping, curated Parquet output — shared by local runs and tests |
| `storage/` | Abstracts local filesystem vs. S3 so calling code never changes |
| `glue_jobs/flat/` | Deployed Glue job script + flat copies of transform/storage (Glue Python Shell can't import a zip) |
| `lambda_handler.py` | Lambda entrypoint: ingests, then triggers Glue |
| `ingestion/backfill.py` | One-off historical pull so trend views have more than "since day one" |
| `scripts/find_locations.py` | Looks up OpenAQ location IDs for a city or country |
| `db/athena_schema.sql` | Athena external table DDL (what actually ran) |
| `metrics/metrics_athena.sql` | Three Athena views the dashboards query |
| `db/schema.sql`, `metrics/metrics.sql` | Redshift variants with `DISTKEY`/`SORTKEY` — written, not yet run |
| `infra/iam/` | IAM trust and permission policies for Lambda and Glue roles |
| `infra/architecture.md` | Pipeline diagram and design decisions |
| `infra/aws_deployment.md` | Console walkthrough of what ran, including every failure hit along the way |
| `docs/` | Exported QuickSight dashboard PDFs |
| `tests/` | 22 unit tests, no AWS account needed |

---

## Data quality

Three distinct problems, each handled differently.

**Sentinel values** (`-1`, `-999`, `9999`, `99999`) are OpenAQ's way of flagging a bad sensor read — they mean "no valid reading," not a real measurement. These are dropped before anything hits the curated table. Not theoretical: a single real ingestion run surfaced 19 `9999.0` readings that the original `value >= 0` check let through, since they aren't negative.

**Extreme outliers** (PM2.5 above 500 µg/m³ — the 2013 Beijing "airpocalypse" peaked under 1000) are flagged via `is_extreme_outlier` but kept, not dropped. A real extreme pollution event is rare but possible; most readings this high are miscalibrated sensors, and those are worth surfacing for review rather than silently discarding. Metric views exclude flagged rows from averages; `vw_flagged_outliers` lists them separately.

**Silent field-name mismatch** — the subtler one. The first deployed run produced zero curated rows from a non-empty raw file. The cleaner had been written against assumed field names (`date`, `locationId`, a `parameter` object) that didn't match the actual API response (`datetime`, `locationsId`, no parameter field). Every row failed the date parse and was dropped with no error. Found by reading a raw response directly; `transform/clean_transform.py` now documents the verified field names.

---

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env        # add your OpenAQ API key
python3 -m pytest tests/ -v
python3 lambda_handler.py --local-transform
```

`--local-transform` runs the same cleaning function in-process instead of triggering the deployed Glue job. `STORAGE_BACKEND=local` (the default) writes to `./data/raw/` and `./data/curated/` — no AWS account needed.

To inspect curated output as CSV:

```bash
python -c "import pandas as pd; pd.read_parquet('data/curated/date=YYYY-MM-DD/readings.parquet').to_csv('out.csv', index=False, encoding='utf-8-sig')"
```

---

## Deploying to AWS

Full console walkthrough (including failures encountered) in [`infra/aws_deployment.md`](infra/aws_deployment.md). Short version:

1. Create an S3 bucket
2. Create the Lambda with policies from [`infra/iam/`](infra/iam/); set `STORAGE_BACKEND=s3`, `S3_BUCKET`, `GLUE_JOB_NAME`, `OPENAQ_API_KEY`, `OPENAQ_PAGE_LIMIT=50`
3. Create the Glue Python Shell job from `glue_jobs/flat/` — helper modules upload to S3 as individual `.py` files, not a zip (Glue Python Shell limitation)
4. Run the Lambda once and confirm curated Parquet appears in S3
5. In Athena: run `db/athena_schema.sql` → `MSCK REPAIR TABLE air_quality_curated;` → `metrics/metrics_athena.sql`
6. Point QuickSight at the three metric views
7. Wire up an EventBridge scheduled rule to trigger the Lambda on your preferred cadence

---

## Backfilling history

`/parameters/{id}/latest` — what regular ingestion uses — returns only a station's single most recent reading. That's fine for "what's the air quality right now" and useless for a week-over-week trend chart on day one.

`ingestion/backfill.py` pulls real hourly history via `/sensors/{sensor_id}/measurements`:

```bash
python -m scripts.find_locations --country US --search "san francisco"
# add the location IDs to BACKFILL_LOCATION_IDS in .env, then:
python -m ingestion.backfill
```

Backfilled data writes into the same `raw/date=YYYY-MM-DD/` partitions as regular ingestion, keyed by each reading's own date rather than the day the backfill ran, so `clean_transform.py` picks it up without any special-casing.

Two undocumented API quirks found during implementation: the historical endpoint is `/sensors/{sensor_id}/measurements`, not `/locations/{id}/measurements` (that 404s). And its date range params are `datetime_from`/`datetime_to` — the more intuitive `date_from`/`date_to` are silently ignored rather than erroring. Both confirmed against the live API.

---

## Sample output

From an actual curated run (`data/curated/date=2026-08-28/readings.parquet`):

| location_id | city | country | parameter | value | unit | date_utc |
|---|---|---|---|---|---|---|
| 1772963 | GBU | US | pm25 | 9.0 | µg/m³ | 2025-08-09 14:00:00+00:00 |
| 1066093 | SCIOTO | US | pm25 | 13.8 | µg/m³ | 2026-08-28 01:00:00+00:00 |
| 2146563 | Białystok | PL | pm25 | 6.0 | µg/m³ | 2024-12-09 12:00:00+00:00 |
| 10819 | Yinnar | AU | pm25 | 8.19 | µg/m³ | 2026-07-29 19:00:00+00:00 |
| 2954721 | San Francisco-Oakland-Fremont | US | pm25 | 0.0 | µg/m³ | 2026-07-03 07:00:00+00:00 |
| 2954722 | San Francisco-Oakland-Fremont | US | pm25 | 4.0 | µg/m³ | 2026-08-28 01:00:00+00:00 |

That run: 1,000 readings pulled, 903 of 999 unique stations resolved to city/country (the rest hit OpenAQ rate limits or stale location IDs), 989 clean rows after filtering and deduplication.

---

## Curated table (Athena)

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS air_quality_curated (
    location_id         BIGINT,
    location_name       STRING,
    city                STRING,
    country             STRING,
    parameter           STRING,
    value               DOUBLE,
    unit                STRING,
    date_utc            TIMESTAMP,
    is_extreme_outlier  BOOLEAN
)
PARTITIONED BY (`date` STRING)
STORED AS PARQUET
LOCATION 's3://YOUR_BUCKET_NAME/curated/'
TBLPROPERTIES ('parquet.compression' = 'SNAPPY');
```

Run `MSCK REPAIR TABLE air_quality_curated;` after each new `date=` partition appears. Full DDL in [`db/athena_schema.sql`](db/athena_schema.sql).

A Redshift variant with `DISTKEY (location_id)` and `SORTKEY (date_utc)` is in [`db/schema.sql`](db/schema.sql) — the sort/dist keys are there because nearly every query filters by date range and joins on station — but it has not been run against a live Redshift cluster.

---

## What's next

The dashboards are early snapshots — the pipeline runs on demand, so city comparisons currently reflect single readings from different days. Scheduling daily EventBridge ingestion is the obvious next step: once a few weeks of history accumulate, the week-over-week trend views become meaningful findings rather than placeholders.

---

*Author: Deeksha Moole*
