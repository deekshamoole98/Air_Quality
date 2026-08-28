"""
Ingestion entrypoint: fetch latest readings from OpenAQ, attach resolved
location metadata, and land the result as raw JSON.

This step deliberately does NOT filter or clean anything — raw data is
kept as-is (including any bad values) so the pipeline has an unmodified
source of truth to reprocess from if the cleaning logic ever changes.
Cleaning happens downstream in transform/clean_transform.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import config
from ingestion.openaq_client import fetch_latest_readings, fetch_location_metadata_bulk
from storage.storage import write_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_ingestion() -> str:
    """Fetch readings + location metadata, land as one raw JSON file. Returns the path/URI written."""
    logger.info("Fetching latest PM2.5 readings from OpenAQ...")
    readings = fetch_latest_readings()
    logger.info("Fetched %d readings", len(readings))

    location_ids = [r.get("locationsId") for r in readings if r.get("locationsId") is not None]
    logger.info("Resolving metadata for %d unique locations...", len(set(location_ids)))
    location_metadata = fetch_location_metadata_bulk(location_ids)

    enriched = []
    for r in readings:
        loc_id = r.get("locationsId")
        meta = location_metadata.get(loc_id, {})
        enriched.append({**r, "location_meta": meta})

    now = datetime.now(timezone.utc)
    key = f"date={now:%Y-%m-%d}/run_{now:%H%M%S}.json"
    location = write_json(config.S3_RAW_PREFIX, key, enriched)
    logger.info("Ingestion complete: %s", location)
    return location


if __name__ == "__main__":
    run_ingestion()
