"""
Transform raw ingested readings into a curated, analysis-ready dataset.

Responsibilities (deliberately kept separate from ingestion so each can
be tested/rerun independently):
  1. Filter out invalid/sentinel values (e.g. the -1.0 readings seen in
     the original pipeline, which are OpenAQ's way of flagging a missing
     or invalid sensor value, not a real reading of -1 µg/m³).
  2. Deduplicate readings (the same location + timestamp can appear
     more than once across overlapping ingestion runs).
  3. Flatten the nested location metadata into flat city/country columns.
  4. Write the result as Parquet, partitioned by date, ready to be
     queried directly (Athena) or loaded into Redshift.
"""
from __future__ import annotations

import logging

import pandas as pd

import config
from storage.storage import list_keys, read_json

logger = logging.getLogger(__name__)


def _flatten(record: dict) -> dict:
    meta = record.get("location_meta", {}) or {}
    date_info = record.get("datetime", {}) or {}
    return {
        "location_id": record.get("locationsId"),
        "location_name": meta.get("name"),
        "city": meta.get("city"),
        "country": meta.get("country"),
        "parameter": config.OPENAQ_PARAMETER_NAME,
        "value": record.get("value"),
        "unit": config.OPENAQ_PARAMETER_UNIT,
        "date_utc": date_info.get("utc") if isinstance(date_info, dict) else record.get("date_utc"),
    }


def clean_readings(raw_records: list[dict]) -> pd.DataFrame:
    """Apply data quality rules to a list of raw reading dicts and return a clean DataFrame."""
    if not raw_records:
        return pd.DataFrame(
            columns=["location_id", "location_name", "city", "country", "parameter", "value", "unit", "date_utc"]
        )

    df = pd.DataFrame([_flatten(r) for r in raw_records])

    before = len(df)
    df = df[df["value"] >= config.MIN_VALID_VALUE]
    dropped_invalid = before - len(df)

    before = len(df)
    df = df.drop_duplicates(subset=["location_id", "parameter", "date_utc"])
    dropped_dupes = before - len(df)

    df["date_utc"] = pd.to_datetime(df["date_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["date_utc"])

    logger.info(
        "Cleaning summary: %d invalid values dropped, %d duplicates dropped, %d rows remaining",
        dropped_invalid,
        dropped_dupes,
        len(df),
    )
    return df


def run_transform_for_date(date_str: str) -> pd.DataFrame:
    """Read all raw files for a given date (YYYY-MM-DD), clean them, and write curated Parquet."""
    keys = [k for k in list_keys(config.S3_RAW_PREFIX) if k.startswith(f"date={date_str}")]
    if not keys:
        logger.warning("No raw files found for date=%s", date_str)
        return pd.DataFrame()

    all_records: list[dict] = []
    for key in keys:
        all_records.extend(read_json(config.S3_RAW_PREFIX, key))

    df = clean_readings(all_records)
    if df.empty:
        logger.warning("No valid rows after cleaning for date=%s", date_str)
        return df

    _write_curated(df, date_str)
    return df


def _write_curated(df: pd.DataFrame, date_str: str) -> None:
    if config.STORAGE_BACKEND == "local":
        from pathlib import Path

        out_dir = Path(config.LOCAL_DATA_DIR) / config.S3_CURATED_PREFIX / f"date={date_str}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "readings.parquet"
        df.to_parquet(out_path, index=False)
        logger.info("Wrote curated data: %s (%d rows)", out_path, len(df))

    elif config.STORAGE_BACKEND == "s3":
        import boto3
        import io

        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False)
        buffer.seek(0)
        s3 = boto3.client("s3", region_name=config.AWS_REGION)
        key = f"{config.S3_CURATED_PREFIX}/date={date_str}/readings.parquet"
        s3.put_object(Bucket=config.S3_BUCKET, Key=key, Body=buffer.getvalue())
        logger.info("Wrote curated data: s3://%s/%s (%d rows)", config.S3_BUCKET, key, len(df))

    else:
        raise ValueError(f"Unknown STORAGE_BACKEND: {config.STORAGE_BACKEND}")


if __name__ == "__main__":
    import sys
    from datetime import datetime, timezone

    date_arg = sys.argv[1] if len(sys.argv) > 1 else f"{datetime.now(timezone.utc):%Y-%m-%d}"
    run_transform_for_date(date_arg)
