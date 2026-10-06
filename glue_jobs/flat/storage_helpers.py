"""
Storage abstraction: local filesystem (dev) or S3 (deployed), chosen by
config.STORAGE_BACKEND.

  raw/date=YYYY-MM-DD/<run_id>.json        -- untouched API responses
  curated/date=YYYY-MM-DD/readings.parquet -- cleaned, deduped output
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


def _local_path(prefix: str, key: str) -> Path:
    path = Path(config.LOCAL_DATA_DIR) / prefix / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_json(prefix: str, key: str, payload: list[dict] | dict) -> str:
    if config.STORAGE_BACKEND == "local":
        path = _local_path(prefix, key)
        path.write_text(json.dumps(payload, indent=2, default=str))
        logger.info("Wrote %s", path)
        return str(path)

    elif config.STORAGE_BACKEND == "s3":
        import boto3  # lazy, so local dev doesn't need boto3

        s3 = boto3.client("s3", region_name=config.AWS_REGION)
        full_key = f"{prefix}/{key}"
        s3.put_object(
            Bucket=config.S3_BUCKET,
            Key=full_key,
            Body=json.dumps(payload, default=str).encode("utf-8"),
        )
        uri = f"s3://{config.S3_BUCKET}/{full_key}"
        logger.info("Wrote %s", uri)
        return uri

    raise ValueError(f"Unknown STORAGE_BACKEND: {config.STORAGE_BACKEND}")


def read_json(prefix: str, key: str) -> Any:
    if config.STORAGE_BACKEND == "local":
        return json.loads(_local_path(prefix, key).read_text())

    elif config.STORAGE_BACKEND == "s3":
        import boto3

        s3 = boto3.client("s3", region_name=config.AWS_REGION)
        obj = s3.get_object(Bucket=config.S3_BUCKET, Key=f"{prefix}/{key}")
        return json.loads(obj["Body"].read())

    raise ValueError(f"Unknown STORAGE_BACKEND: {config.STORAGE_BACKEND}")


def list_keys(prefix: str) -> list[str]:
    if config.STORAGE_BACKEND == "local":
        base = Path(config.LOCAL_DATA_DIR) / prefix
        if not base.exists():
            return []
        return [p.relative_to(base).as_posix() for p in base.rglob("*.json")]

    elif config.STORAGE_BACKEND == "s3":
        import boto3

        s3 = boto3.client("s3", region_name=config.AWS_REGION)
        keys = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=config.S3_BUCKET, Prefix=f"{prefix}/"):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"][len(prefix) + 1:])
        return keys

    raise ValueError(f"Unknown STORAGE_BACKEND: {config.STORAGE_BACKEND}")
