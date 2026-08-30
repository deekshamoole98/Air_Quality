"""
One-off historical backfill for a fixed set of locations
(config.BACKFILL_LOCATION_IDS), so trend/week-over-week metrics have more
than "since I started running this" to work with.

Writes into the same raw/date=YYYY-MM-DD/ partitions regular ingestion
writes to, grouped by each reading's own date — not the day the backfill
was run — so the existing transform step picks it up with zero
special-casing. Run once (or whenever you add a new location to backfill):

    python -m ingestion.backfill
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import config
from ingestion.openaq_client import fetch_location_metadata, fetch_measurements
from storage.storage import write_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_backfill() -> list[str]:
    if not config.BACKFILL_LOCATION_IDS:
        logger.warning("BACKFILL_LOCATION_IDS is empty — nothing to backfill. Set it in .env.")
        return []

    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=config.BACKFILL_DAYS)
    written: list[str] = []

    for location_id in config.BACKFILL_LOCATION_IDS:
        logger.info(
            "Backfilling location %s (%s to %s)...", location_id, date_from.date(), date_to.date()
        )
        meta = fetch_location_metadata(location_id)
        measurements = fetch_measurements(
            location_id,
            date_from.strftime("%Y-%m-%d"),
            date_to.strftime("%Y-%m-%d"),
            limit=config.BACKFILL_DAYS * 24,
        )
        logger.info("Fetched %d historical readings for location %s", len(measurements), location_id)

        by_date: dict[str, list[dict]] = defaultdict(list)
        for m in measurements:
            utc = m.get("datetime", {}).get("utc")
            if not utc:
                continue
            by_date[utc[:10]].append({**m, "location_meta": meta})

        for day, records in by_date.items():
            key = f"date={day}/backfill_location_{location_id}.json"
            written.append(write_json(config.S3_RAW_PREFIX, key, records))

    logger.info(
        "Backfill complete: wrote %d raw files across %d locations", len(written), len(config.BACKFILL_LOCATION_IDS)
    )
    return written


if __name__ == "__main__":
    run_backfill()
