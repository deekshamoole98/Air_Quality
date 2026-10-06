"""
Central configuration, loaded entirely from environment variables.

No secrets or environment-specific values are hardcoded here. Locally,
values are read from a `.env` file (via python-dotenv); in AWS Lambda,
they should be set as Lambda environment variables (backed by
Secrets Manager / SSM Parameter Store for the API key).
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env and fill it in for local runs."
        )
    return value


# --- OpenAQ API ---
# OPENAQ_API_KEY is deliberately NOT read at import time (unlike the other
# settings below) — code that only runs the transform step (e.g. the Glue
# job) never calls the OpenAQ API and shouldn't need this key in its
# environment just to import config. Call get_openaq_api_key() instead.
OPENAQ_BASE_URL = os.environ.get("OPENAQ_BASE_URL", "https://api.openaq.org/v3")
OPENAQ_PARAMETER_ID = int(os.environ.get("OPENAQ_PARAMETER_ID", "2"))  # 2 = pm25
OPENAQ_PARAMETER_NAME = os.environ.get("OPENAQ_PARAMETER_NAME", "pm25")
OPENAQ_PARAMETER_UNIT = os.environ.get("OPENAQ_PARAMETER_UNIT", "µg/m³")
OPENAQ_PAGE_LIMIT = int(os.environ.get("OPENAQ_PAGE_LIMIT", "1000"))


def get_openaq_api_key() -> str:
    """Only raises when actually called — i.e. only for code that talks to OpenAQ."""
    return _require("OPENAQ_API_KEY")

# --- Storage backend ---
# "local" writes to the local filesystem (./data/...) for development.
# "s3" writes to the configured S3 bucket — used in the deployed pipeline.
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_RAW_PREFIX = os.environ.get("S3_RAW_PREFIX", "raw")
S3_CURATED_PREFIX = os.environ.get("S3_CURATED_PREFIX", "curated")
LOCAL_DATA_DIR = os.environ.get("LOCAL_DATA_DIR", "./data")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# --- Data quality thresholds ---
# OpenAQ occasionally returns sentinel values for missing/errored sensor
# readings, on both ends of the range — e.g. -1 or exactly 9999. These are
# dropped outright since they're not real measurements, not just low readings.
MIN_VALID_VALUE = float(os.environ.get("MIN_VALID_VALUE", "0"))
SENTINEL_VALUES = {-1, -999, 9999, 99999}

# Ambient PM2.5 essentially never exceeds this in practice (even severe
# events, e.g. the 2013 Beijing "airpocalypse", topped out under 1000).
# Readings above this are FLAGGED (kept, not dropped) via the
# `is_extreme_outlier` column so they can be reviewed downstream rather
# than silently discarded — a real extreme event is rare but possible,
# and a miscalibrated sensor (what's actually behind most values this
# high) is a finding worth surfacing, not hiding.
MAX_PLAUSIBLE_VALUE = float(os.environ.get("MAX_PLAUSIBLE_VALUE", "500"))

# WHO 24-hour PM2.5 guideline (µg/m³), used for the threshold-breach metric.
WHO_PM25_24H_GUIDELINE = float(os.environ.get("WHO_PM25_24H_GUIDELINE", "15"))

# --- Backfill (historical pull, so trend metrics have more than "since
# I started running this" to work with) ---
# Comma-separated OpenAQ location ids, e.g. "1772963,2954721,8152".
# Find ids for cities you care about with scripts/find_locations.py.
BACKFILL_LOCATION_IDS = [
    int(x) for x in os.environ.get("BACKFILL_LOCATION_IDS", "").split(",") if x.strip()
]
BACKFILL_DAYS = int(os.environ.get("BACKFILL_DAYS", "60"))
