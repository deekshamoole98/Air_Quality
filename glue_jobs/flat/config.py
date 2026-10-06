"""
Central configuration, loaded entirely from environment variables.

Locally, values are read from a `.env` file (via python-dotenv, if installed).
In AWS Lambda/Glue, environment variables are set by the service, so the dotenv
import is optional.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # not installed -- fine in Lambda/Glue


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env and fill it in for local runs."
        )
    return value


# --- OpenAQ API ---
# The key is only required when something actually calls the API (ingestion),
# so a transform-only environment like Glue doesn't need it.
OPENAQ_BASE_URL = os.environ.get("OPENAQ_BASE_URL", "https://api.openaq.org/v3")
OPENAQ_PARAMETER_ID = int(os.environ.get("OPENAQ_PARAMETER_ID", "2"))  # 2 = pm25
OPENAQ_PAGE_LIMIT = int(os.environ.get("OPENAQ_PAGE_LIMIT", "1000"))


def get_openaq_api_key() -> str:
    return _require("OPENAQ_API_KEY")


# --- Storage backend ---
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_RAW_PREFIX = os.environ.get("S3_RAW_PREFIX", "raw")
S3_CURATED_PREFIX = os.environ.get("S3_CURATED_PREFIX", "curated")
LOCAL_DATA_DIR = os.environ.get("LOCAL_DATA_DIR", "./data")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# --- Data quality thresholds ---
# Sentinel values mean "no valid reading", not a measurement. Dropped outright.
MIN_VALID_VALUE = float(os.environ.get("MIN_VALID_VALUE", "0"))
SENTINEL_VALUES = {-1, -999, 9999, 99999}

# Values above this are kept but flagged (is_extreme_outlier).
MAX_PLAUSIBLE_VALUE = float(os.environ.get("MAX_PLAUSIBLE_VALUE", "500"))

# WHO 24-hour PM2.5 guideline (ug/m3).
WHO_PM25_24H_GUIDELINE = float(os.environ.get("WHO_PM25_24H_GUIDELINE", "15"))

# --- Backfill ---
BACKFILL_LOCATION_IDS = [
    int(x) for x in os.environ.get("BACKFILL_LOCATION_IDS", "").split(",") if x.strip()
]
BACKFILL_DAYS = int(os.environ.get("BACKFILL_DAYS", "60"))
