# Air Quality Reporting Pipeline

Pulls PM2.5 readings from the [OpenAQ](https://openaq.org) API, cleans them up, and lands them somewhere a BI tool can actually query. Built on AWS (Lambda, S3, Glue, Athena, QuickSight), since the goal was something I could actually deploy, not just a local script.

## Status: what's actually verified vs. what's just code

Being upfront about this rather than letting the architecture diagram imply more than what's true:

**Verified: ran for real, more than once**
- The full AWS path in my own account: Lambda pulls from OpenAQ → raw JSON in S3 → Glue Python Shell job cleans it → curated Parquet in S3 → Athena table and views → QuickSight dashboards. Exported snapshots are in [`docs/`](docs/).
- Ingestion → cleaning → curated Parquet locally (`--local-transform`)
- Sentinel filtering and outlier flagging. Both caught real bad values in real ingested data, not just hypothetical test cases
- The backfill client and the location metadata cache, checked against live OpenAQ responses, including finding and working around two undocumented quirks (see "Backfilling history" below)
- 22 unit tests, all passing

**Limits: read these before treating it as production**
- **It runs on demand.** An hourly EventBridge schedule is documented but not enabled.
- **The data is thin.** `/latest` returns one reading per station, and many are months old, so the dashboards are early snapshots (roughly one reading per city), not findings. The week-over-week views need weeks of accumulated history before they say anything.
- **The API key is a Lambda environment variable**, not Secrets Manager.
- **Redshift is untested.** `db/schema.sql` and `metrics/metrics.sql` were written and reviewed, but never run against Redshift. Athena is what actually ran.
- **QuickSight isn't left running.** It bills per user with no pause option, so I captured the dashboards as PDFs instead of keeping a subscription going.

If you're using this as a portfolio piece: the pipeline logic is solid, and the debugging trail (silently dropped rows from wrong field names, sentinel values, a Glue runtime that can't import zipped packages) is worth walking an interviewer through. It's catalogued in [`infra/aws_deployment.md`](infra/aws_deployment.md).

## Why

The question I actually care about: which cities/regions are consistently over WHO's air quality guideline, and is it getting better or worse week to week? Answering that once is a five-minute query. Answering it *every week without redoing the work* is what this pipeline is for.

## How it fits together

```
Lambda (ingest) → OpenAQ API → S3 (raw JSON)
                             → Glue Python Shell job (clean) → S3 (curated, Parquet)
                             → Athena table + metric views → QuickSight
```

The transform runs as its own Glue job rather than inside the Lambda, which keeps the Lambda thin and gives cleaning its own compute, logs and IAM role.

One honest wrinkle: a Glue **Python Shell** job can't import a zip of packages, so the Glue job uses flat copies of the cleaning code in [`glue_jobs/flat/`](glue_jobs/flat/). It's the same logic as `transform/` and `storage/`, duplicated by necessity, so changes need to be made in both places. Full diagram and notes are in [`infra/architecture.md`](infra/architecture.md); the step-by-step deployment is in [`infra/aws_deployment.md`](infra/aws_deployment.md).

## What's in here

| Path | Purpose |
|---|---|
| `config.py` | All config, read from env vars. Nothing hardcoded |
| `ingestion/` | Talks to the OpenAQ API, lands raw JSON |
| `transform/` | Cleaning, deduping, curated Parquet output. Used by local runs and tests |
| `storage/` | Swap between local filesystem and S3 without touching calling code |
| `glue_jobs/flat/` | The Glue job script plus flat copies of the cleaning code, which is what's deployed to Glue |
| `lambda_handler.py` | Lambda entrypoint: ingests, then triggers the Glue job |
| `ingestion/backfill.py` | One-off historical pull for a fixed set of locations, so trend metrics have more than "since I started running this" |
| `scripts/find_locations.py` | Look up OpenAQ location ids for a city/country to feed into backfill |
| `db/athena_schema.sql` | Athena external table over the curated Parquet (what actually ran) |
| `metrics/metrics_athena.sql` | The three Athena views the dashboards are built on |
| `db/schema.sql`, `metrics/metrics.sql` | Redshift variants, written but never run |
| `infra/aws_deployment.md` | Console walkthrough of what actually ran, plus a table of every failure hit along the way |
| `infra/iam/` | IAM trust and permission policies for the Lambda and Glue roles |
| `infra/architecture.md` | Diagram and notes |
| `docs/` | Exported dashboard PDFs |
| `tests/` | Unit tests, no AWS account needed |

## Running it locally

```bash
pip install -r requirements.txt
cp .env.example .env   # drop your OpenAQ API key in here
python3 -m pytest tests/ -v
python3 lambda_handler.py --local-transform    # runs ingest + transform in-process, no AWS needed
```

`--local-transform` matters here: without it, `lambda_handler.py` tries to trigger the real Glue job via `boto3`, which needs AWS credentials and a deployed job. The flag runs the same cleaning function in-process instead.

Default `STORAGE_BACKEND=local` writes to `./data/raw/` and `./data/curated/`, so you can run the whole thing without touching AWS. Curated output is Parquet, which isn't great for a quick look. If you want a CSV to open in Excel:

```bash
python -c "import pandas as pd; pd.read_parquet('data/curated/date=YYYY-MM-DD/readings.parquet').to_csv('data/curated/date=YYYY-MM-DD/readings.csv', index=False, encoding='utf-8-sig')"
```

## Deploying

The full console walkthrough is in [`infra/aws_deployment.md`](infra/aws_deployment.md). The short version:

1. Create an S3 bucket.
2. Create the Lambda (IAM policies in [`infra/iam/`](infra/iam/)). Set `STORAGE_BACKEND=s3`, `S3_BUCKET`, `GLUE_JOB_NAME`, `OPENAQ_API_KEY` and `OPENAQ_PAGE_LIMIT=50`.
3. Create the Glue Python Shell job from the files in `glue_jobs/flat/`. The helper modules are uploaded to S3 as individual `.py` files, not a zip.
4. Run the Lambda once and confirm a Glue run succeeds and `curated/` appears in S3.
5. In Athena, run `db/athena_schema.sql`, `MSCK REPAIR TABLE air_quality_curated;`, then the views in `metrics/metrics_athena.sql`.
6. Point QuickSight at the views (and mind the cost: see Status above).
7. Optional: add an EventBridge schedule to trigger the Lambda.

## Data quality: sentinel values and outliers

Two separate problems, handled two different ways:

- **Sentinel values** (`-1`, `-999`, `9999`, `99999`, and `-9999`, which the `>= 0` floor catches) mean "no valid reading," not a real measurement. It's OpenAQ's way of flagging a bad sensor read. These get dropped outright. This one's not theoretical: a single real ingestion run turned up nineteen `9999` readings that the original `value >= 0` check let straight through, since they're not negative.
- **Implausibly high values** (PM2.5 over `MAX_PLAUSIBLE_VALUE`, default 500 µg/m³; even the 2013 Beijing "airpocalypse" stayed under 1000) are *kept*, not dropped, but flagged via `is_extreme_outlier`. A real extreme pollution event is rare but possible; what's actually behind most readings this high is a miscalibrated sensor, and that's worth surfacing for review, not silently discarding. `metrics/metrics.sql` excludes flagged rows from averages and has `vw_flagged_outliers` to list them. The Athena views behind the dashboards do **not** exclude them (noted in the file; add `AND NOT is_extreme_outlier` to do so).

A third problem was worse because it was silent: the first deployed run produced **zero** curated rows from a non-empty raw file. The cleaner assumed field names (`date`, `locationId`, a `parameter` object) that the real API doesn't use (`datetime`, `locationsId`, no parameter field), so every row failed the date check and was dropped without an error. It was only found by reading an actual raw response, which is why `transform/clean_transform.py` now documents the verified field names.

## Backfilling history

`/parameters/{id}/latest` (what regular ingestion uses) only ever returns each station's single most recent reading, which is fine for "what's the air like right now" and useless for a week-over-week trend chart on day one. `ingestion/backfill.py` pulls real hourly history instead, via `/sensors/{sensor_id}/measurements`:

```bash
python -m scripts.find_locations --country US --search "san francisco"   # find location ids
# put the ids you want into BACKFILL_LOCATION_IDS in .env, then:
python -m ingestion.backfill
```

It writes into the same `raw/date=YYYY-MM-DD/` partitions regular ingestion uses, grouped by each reading's *own* date and not the day the backfill ran, so `transform/clean_transform.py` picks it up with zero special-casing.

(Worth noting since it wasn't obvious from the API docs: the historical endpoint is `/sensors/{sensor_id}/measurements`, not `/locations/{id}/measurements`, which 404s. And its date-range params are `datetime_from`/`datetime_to`; the more intuitive `date_from`/`date_to` are silently ignored rather than erroring. Both confirmed against the live API before shipping this.)

## Dashboards

Built in QuickSight on the three Athena views. Exported PDFs: [overview](docs/dashboard_overview.pdf) and [week-over-week](docs/dashboard_week_over_week.pdf).

Treat these as proof the pipeline works end to end, not as findings:
- Each city has about one reading, so city and country rankings compare single readings from different days.
- The daily and breach views keep only the last 7 days, because `/latest` otherwise feeds in readings that are months or years old.
- The week-over-week sheet is mostly empty or misleading until a few weeks of data exist. The KPI there compares dates years apart.
- In the overview, the KPI's "% change" is computed against `reading_count` and means nothing, and the "daily trend" line connects different cities.

What I'd do next: schedule ingestion daily so real history accumulates, then rebuild the trend sheets.

## Metrics

- Daily average PM2.5 by city (last 7 days)
- % of readings over the WHO 24-hour PM2.5 guideline (15 µg/m³) (last 7 days)
- Week-over-week change in average PM2.5 by city
- Flagged extreme outliers, for manual review (Redshift variant only)

Definitions live in [`metrics/metrics_athena.sql`](metrics/metrics_athena.sql) (what ran) and [`metrics/metrics.sql`](metrics/metrics.sql) (Redshift).

## Sample output

A few rows from an actual curated run (`data/curated/date=2026-08-28/readings.parquet`):

| location_id | city | country | parameter | value | unit | date_utc |
|---|---|---|---|---|---|---|
| 1772963 | GBU | US | pm25 | 9.0 | µg/m³ | 2025-08-09 14:00:00+00:00 |
| 1066093 | SCIOTO | US | pm25 | 13.8 | µg/m³ | 2026-08-28 01:00:00+00:00 |
| 2146563 | Białystok | PL | pm25 | 6.0 | µg/m³ | 2024-12-09 12:00:00+00:00 |
| 10819 | Yinnar | AU | pm25 | 8.19 | µg/m³ | 2026-07-29 19:00:00+00:00 |
| 2954721 | San Francisco-Oakland-Fremont | US | pm25 | 0.0 | µg/m³ | 2026-07-03 07:00:00+00:00 |
| 2954722 | San Francisco-Oakland-Fremont | US | pm25 | 4.0 | µg/m³ | 2026-08-28 01:00:00+00:00 |

That run pulled 1000 readings, resolved location metadata for 903 of 999 unique stations (the rest hit OpenAQ rate limits or a stale location id), and landed 989 clean rows after filtering and deduping.

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

New `date=` folders only become visible after `MSCK REPAIR TABLE air_quality_curated;`. Full DDL is in [`db/athena_schema.sql`](db/athena_schema.sql). The Redshift variant in [`db/schema.sql`](db/schema.sql) uses `DISTKEY (location_id)` to keep a station's rows together and `SORTKEY (date_utc)` since nearly every query filters by date range; it has never been run.

## Author

Deeksha Moole