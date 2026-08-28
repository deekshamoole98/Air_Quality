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
OPENAQ_API_KEY = _require("OPENAQ_API_KEY")
OPENAQ_BASE_URL = os.environ.get("OPENAQ_BASE_URL", "https://api.openaq.org/v3")
OPENAQ_PARAMETER_ID = int(os.environ.get("OPENAQ_PARAMETER_ID", "2"))  # 2 = pm25
OPENAQ_PARAMETER_NAME = os.environ.get("OPENAQ_PARAMETER_NAME", "pm25")
OPENAQ_PARAMETER_UNIT = os.environ.get("OPENAQ_PARAMETER_UNIT", "µg/m³")
OPENAQ_PAGE_LIMIT = int(os.environ.get("OPENAQ_PAGE_LIMIT", "1000"))

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
# OpenAQ occasionally returns sentinel values (e.g. -1, -999) for missing
# sensor readings. Any value below this floor is dropped during cleaning.
MIN_VALID_VALUE = float(os.environ.get("MIN_VALID_VALUE", "0"))

# WHO 24-hour PM2.5 guideline (µg/m³), used for the threshold-breach metric.
WHO_PM25_24H_GUIDELINE = float(os.environ.get("WHO_PM25_24H_GUIDELINE", "15"))
