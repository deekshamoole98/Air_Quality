# Air Quality Reporting Pipeline

Pulls PM2.5 readings from the [OpenAQ](https://openaq.org) API, cleans them up, and lands them somewhere a BI tool can actually query. Built around AWS services I already had access to (Lambda, S3, EventBridge, Redshift/Athena), since the goal was something I could actually deploy, not just a local script.

## Why

The question I actually care about: which cities/regions are consistently over WHO's air quality guideline, and is it getting better or worse week to week? Answering that once is a five-minute query. Answering it *every week without redoing the work* is what this pipeline is for.

## How it fits together

```
EventBridge (schedule) → Lambda → OpenAQ API → S3 (raw)
                                        → triggers Glue job → transform/clean → S3 (curated, Parquet)
                                        → Redshift/Athena
                                        → metrics views → BI dashboard
```

The transform step runs as its own Glue job rather than inside the Lambda — keeps the Lambda thin and gives cleaning its own compute/logs/IAM role, without duplicating the cleaning logic anywhere. Full diagram and deployment notes are in [`infra/architecture.md`](infra/architecture.md); the Glue-specific setup is in [`infra/glue_setup_guide.md`](infra/glue_setup_guide.md).

## What's in here

| Path | Purpose |
|---|---|
| `config.py` | All config, read from env vars — nothing hardcoded |
| `ingestion/` | Talks to the OpenAQ API, lands raw JSON |
| `transform/` | Cleaning, deduping, curated Parquet output — the logic Glue and local dev both call |
| `glue_jobs/run_transform_glue.py` | Thin Glue entrypoint that wraps `transform/` for deployment |
| `ingestion/backfill.py` | One-off historical pull for a fixed set of locations, so trend metrics have more than "since I started running this" |
| `scripts/find_locations.py` | Look up OpenAQ location ids for a city/country to feed into backfill |
| `storage/` | Swap between local filesystem and S3 without touching calling code |
| `db/schema.sql` | Redshift table DDL |
| `metrics/metrics.sql` | The actual metric views a dashboard would query |
| `lambda_handler.py` | Lambda entrypoint — ingests, then triggers the Glue job |
| `infra/architecture.md` | Diagram + deployment notes |
| `infra/glue_setup_guide.md` | Console walkthrough for setting up the Glue job |
| `tests/` | Unit tests, no AWS account needed |

## Running it locally

```bash
pip install -r requirements.txt
cp .env.example .env   # drop your OpenAQ API key in here
python3 -m pytest tests/ -v
python3 lambda_handler.py --local-transform    # runs ingest + transform in-process, no AWS needed
```

`--local-transform` matters here: without it, `lambda_handler.py` tries to trigger the real Glue job via `boto3`, which needs AWS credentials and a deployed job. The flag runs the exact same cleaning function in-process instead.

Default `STORAGE_BACKEND=local` writes to `./data/raw/` and `./data/curated/`, so you can run the whole thing without touching AWS. Curated output is Parquet, which isn't great for a quick look — if you want a CSV to open in Excel:

```bash
python -c "import pandas as pd; pd.read_parquet('data/curated/date=YYYY-MM-DD/readings.parquet').to_csv('data/curated/date=YYYY-MM-DD/readings.csv', index=False, encoding='utf-8-sig')"
```

## Deploying for real

1. Make an S3 bucket, set `STORAGE_BACKEND=s3` and `S3_BUCKET` on the Lambda.
2. Put the OpenAQ key in Secrets Manager (or SSM Parameter Store) and give the Lambda role read access to it.
3. Zip up `lambda_handler.py` and dependencies, deploy as a Lambda function.
4. Set up the Glue transform job — see [`infra/glue_setup_guide.md`](infra/glue_setup_guide.md) for the full walkthrough (packaging, IAM role, console steps).
5. Set `GLUE_JOB_NAME` on the Lambda and give its role `glue:StartJobRun`.
6. Wire up an EventBridge schedule to trigger the Lambda (example expression in `infra/architecture.md`).
7. Create the Redshift table from `db/schema.sql`, then either `COPY` the curated Parquet in or query it directly via Redshift Spectrum/Athena.
8. Run `metrics/metrics.sql` to stand up the metric views.
9. Point QuickSight/Tableau/whatever at those views.

## Data quality: sentinel values and outliers

Two separate problems, handled two different ways:

- **Sentinel values** (`-1`, `-999`, `9999`, `99999`) mean "no valid reading," not a real measurement — OpenAQ's way of flagging a bad sensor read. These get dropped outright. This one's not theoretical: a single real ingestion run turned up nineteen `9999` readings that the original `value >= 0` check let straight through, since they're not negative.
- **Implausibly high values** (PM2.5 over `MAX_PLAUSIBLE_VALUE`, default 500 µg/m³ — even the 2013 Beijing "airpocalypse" stayed under 1000) are *kept*, not dropped, but flagged via `is_extreme_outlier`. A real extreme pollution event is rare but possible; what's actually behind most readings this high is a miscalibrated sensor, and that's worth surfacing for review, not silently discarding. The metric views exclude flagged rows from averages; `vw_flagged_outliers` lists them separately.

## Backfilling history

`/parameters/{id}/latest` (what regular ingestion uses) only ever returns each station's single most recent reading — fine for "what's the air like right now," useless for a week-over-week trend chart on day one. `ingestion/backfill.py` pulls real hourly history instead, via `/sensors/{sensor_id}/measurements`:

```bash
python -m scripts.find_locations --country US --search "san francisco"   # find location ids
# put the ids you want into BACKFILL_LOCATION_IDS in .env, then:
python -m ingestion.backfill
```

It writes into the same `raw/date=YYYY-MM-DD/` partitions regular ingestion uses — grouped by each reading's *own* date, not the day the backfill ran — so `transform/clean_transform.py` picks it up with zero special-casing.

(Worth noting since it wasn't obvious from the API docs: the historical endpoint is `/sensors/{sensor_id}/measurements`, not `/locations/{id}/measurements` — that one 404s. And its date-range params are `datetime_from`/`datetime_to`; the more intuitive `date_from`/`date_to` are silently ignored rather than erroring. Both confirmed against the live API before shipping this.)

## Metrics

- Daily average PM2.5 by city (excludes flagged outliers)
- % of readings over the WHO 24-hour PM2.5 guideline (15 µg/m³)
- Week-over-week change in average PM2.5 by city (excludes flagged outliers)
- Flagged extreme outliers, for manual review

Definitions live in [`metrics/metrics.sql`](metrics/metrics.sql).

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

## Curated table (Redshift)

```sql
CREATE TABLE IF NOT EXISTS air_quality_curated (
    location_id         BIGINT,
    location_name       VARCHAR(256),
    city                VARCHAR(128),
    country             VARCHAR(8),
    parameter           VARCHAR(32),
    value               FLOAT,
    unit                VARCHAR(16),
    date_utc            TIMESTAMP,
    is_extreme_outlier  BOOLEAN,
    load_date           DATE DEFAULT CURRENT_DATE
)
DISTSTYLE KEY
DISTKEY (location_id)
SORTKEY (date_utc);
```

`DISTKEY (location_id)` keeps rows for the same station together, and `SORTKEY (date_utc)` is there because basically every query against this table filters by date range. Full DDL in [`db/schema.sql`](db/schema.sql).

## Author

Deeksha Moole
