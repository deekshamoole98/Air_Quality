"""
AWS Lambda entrypoint. Deployed behind an EventBridge scheduled rule
(see infra/architecture.md for the exact schedule expression), this
runs ingestion and then transforms the same day's data.

Kept deliberately thin: all real logic lives in ingestion/ and
transform/ so it can be unit-tested without touching Lambda at all.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ingestion.ingest import run_ingestion
from transform.clean_transform import run_transform_for_date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def handler(event: dict, context) -> dict:
    logger.info("Starting scheduled air quality pipeline run")

    raw_location = run_ingestion()

    today = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    df = run_transform_for_date(today)

    result = {
        "raw_location": raw_location,
        "curated_rows": int(len(df)),
        "date": today,
    }
    logger.info("Pipeline run complete: %s", result)
    return result


if __name__ == "__main__":
    # Local smoke test: `python lambda_handler.py`
    print(handler({}, None))
