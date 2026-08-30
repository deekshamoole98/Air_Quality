"""
AWS Lambda entrypoint. Deployed behind an EventBridge scheduled rule
(see infra/architecture.md), this runs ingestion, then triggers the
Glue job that cleans and curates the same day's raw data.

Note the division of labor: this Lambda only ever does ingestion +
kicking off Glue — it does NOT run transform/clean_transform.py
directly anymore. The cleaning logic runs inside the Glue job
(glue_jobs/run_transform_glue.py), which imports and calls the exact
same tested function. For local development without any AWS calls at
all, use `python lambda_handler.py --local-transform`, which runs the
transform in-process instead of triggering Glue.
"""
from __future__ import annotations

import logging
import os

from ingestion.ingest import run_ingestion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GLUE_JOB_NAME = os.environ.get("GLUE_JOB_NAME", "air-quality-transform")


def _trigger_glue_transform(process_date: str) -> str:
    import boto3

    glue = boto3.client("glue")
    response = glue.start_job_run(
        JobName=GLUE_JOB_NAME,
        Arguments={
            "--BUCKET": os.environ["S3_BUCKET"],
            "--PROCESS_DATE": process_date,
        },
    )
    return response["JobRunId"]


def handler(event: dict, context) -> dict:
    logger.info("Starting scheduled air quality pipeline run")

    raw_location = run_ingestion()

    from datetime import datetime, timezone

    today = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    job_run_id = _trigger_glue_transform(today)

    result = {
        "raw_location": raw_location,
        "glue_job_run_id": job_run_id,
        "date": today,
    }
    logger.info("Pipeline run complete: %s", result)
    return result


if __name__ == "__main__":
    import sys
    from datetime import datetime, timezone

    if "--local-transform" in sys.argv:
        # Dev-only path: run the transform in-process instead of via Glue,
        # so the whole pipeline can be exercised with no AWS calls beyond
        # the OpenAQ API itself (works with STORAGE_BACKEND=local).
        from transform.clean_transform import run_transform_for_date

        raw_location = run_ingestion()
        today = f"{datetime.now(timezone.utc):%Y-%m-%d}"
        df = run_transform_for_date(today)
        print({"raw_location": raw_location, "curated_rows": int(len(df)), "date": today})
    else:
        print(handler({}, None))
