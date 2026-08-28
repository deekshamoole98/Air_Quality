# Air Quality Reporting Pipeline

Pulls PM2.5 readings from the [OpenAQ](https://openaq.org) API, cleans them up, and lands them somewhere a BI tool can actually query. Built around AWS services I already had access to (Lambda, S3, EventBridge, Redshift/Athena), since the goal was something I could actually deploy, not just a local script.

## Why

The question I actually care about: which cities/regions are consistently over WHO's air quality guideline, and is it getting better or worse week to week? Answering that once is a five-minute query. Answering it *every week without redoing the work* is what this pipeline is for.

## How it fits together

```
EventBridge (schedule) → Lambda → OpenAQ API → S3 (raw)
                                        → transform/clean → S3 (curated, Parquet)
                                        → Redshift/Athena
                                        → metrics views → BI dashboard
```

Full diagram and deployment notes are in [`infra/architecture.md`](infra/architecture.md).

## What's in here

| Path | Purpose |
|---|---|
| `config.py` | All config, read from env vars — nothing hardcoded |
| `ingestion/` | Talks to the OpenAQ API, lands raw JSON |
| `transform/` | Cleaning, deduping, curated Parquet output |
| `storage/` | Swap between local filesystem and S3 without touching calling code |
| `db/schema.sql` | Redshift table DDL |
| `metrics/metrics.sql` | The actual metric views a dashboard would query |
| `lambda_handler.py` | Lambda entrypoint, chains ingest → transform |
| `infra/architecture.md` | Diagram + deployment notes |
| `tests/` | Unit tests, no AWS account needed |

## Running it locally

```bash
pip install -r requirements.txt
cp .env.example .env   # drop your OpenAQ API key in here
python3 -m pytest tests/ -v
python3 lambda_handler.py    # runs a full ingest + transform pass
```

Default `STORAGE_BACKEND=local` writes to `./data/raw/` and `./data/curated/`, so you can run the whole thing without touching AWS. Curated output is Parquet, which isn't great for a quick look — if you want a CSV to open in Excel:

```bash
python -c "import pandas as pd; pd.read_parquet('data/curated/date=YYYY-MM-DD/readings.parquet').to_csv('data/curated/date=YYYY-MM-DD/readings.csv', index=False, encoding='utf-8-sig')"
```

## Deploying for real

1. Make an S3 bucket, set `STORAGE_BACKEND=s3` and `S3_BUCKET` on the Lambda.
2. Put the OpenAQ key in Secrets Manager (or SSM Parameter Store) and give the Lambda role read access to it.
3. Zip up `lambda_handler.py` and dependencies, deploy as a Lambda function.
4. Wire up an EventBridge schedule to trigger it (example expression in `infra/architecture.md`).
5. Create the Redshift table from `db/schema.sql`, then either `COPY` the curated Parquet in or query it directly via Redshift Spectrum/Athena.
6. Run `metrics/metrics.sql` to stand up the metric views.
7. Point QuickSight/Tableau/whatever at those views.

## Metrics

- Daily average PM2.5 by city
- % of readings over the WHO 24-hour PM2.5 guideline (15 µg/m³)
- Week-over-week change in average PM2.5 by city

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
    location_id     BIGINT,
    location_name   VARCHAR(256),
    city            VARCHAR(128),
    country         VARCHAR(8),
    parameter       VARCHAR(32),
    value           FLOAT,
    unit            VARCHAR(16),
    date_utc        TIMESTAMP,
    load_date       DATE DEFAULT CURRENT_DATE
)
DISTSTYLE KEY
DISTKEY (location_id)
SORTKEY (date_utc);
```

`DISTKEY (location_id)` keeps rows for the same station together, and `SORTKEY (date_utc)` is there because basically every query against this table filters by date range. Full DDL in [`db/schema.sql`](db/schema.sql).

## Author

Deeksha Moole
