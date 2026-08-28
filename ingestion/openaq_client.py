"""
Thin client around the OpenAQ v3 API.

Responsible only for talking to the API and returning plain Python
dicts/lists — no storage or transformation logic lives here, so it can
be unit-tested in isolation with mocked HTTP responses.

NOTE: OpenAQ's `/parameters/{id}/latest` endpoint returns a `locationsId`
but not the location's city/country. That's why the original version of
this pipeline had null city/country for every row — the location lookup
step was missing. This client adds it back via `/locations/{id}`.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

_SESSION = requests.Session()


def _headers() -> dict:
    return {"X-API-Key": config.OPENAQ_API_KEY}


def _get_with_retry(url: str, params: dict | None = None, max_retries: int = 3) -> dict:
    """GET with basic exponential backoff for transient failures / rate limits."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = _SESSION.get(url, headers=_headers(), params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("Rate limited by OpenAQ, backing off %ss", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            wait = 2 ** attempt
            logger.warning("Request to %s failed (%s), retrying in %ss", url, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"Failed to GET {url} after {max_retries} attempts") from last_exc


def fetch_latest_readings(parameter_id: int | None = None, limit: int | None = None) -> list[dict]:
    """
    Fetch the latest readings for a given parameter (default: PM2.5, id=2).

    Returns a list of raw result dicts as given by the API, each expected
    to contain at least: locationsId, value, and a datetime object.
    Handles pagination up to the requested limit.
    """
    parameter_id = parameter_id or config.OPENAQ_PARAMETER_ID
    limit = limit or config.OPENAQ_PAGE_LIMIT
    url = f"{config.OPENAQ_BASE_URL}/parameters/{parameter_id}/latest"

    results: list[dict] = []
    page = 1
    page_size = min(limit, 1000)  # OpenAQ v3 page size cap

    while len(results) < limit:
        data = _get_with_retry(url, params={"limit": page_size, "page": page})
        batch = data.get("results", [])
        if not batch:
            break
        results.extend(batch)
        if len(batch) < page_size:
            break  # last page
        page += 1

    return results[:limit]


def fetch_location_metadata(location_id: int) -> dict:
    """
    Look up city/country/name for a single location id.

    OpenAQ v3 locations don't always have a clean `city` field —
    fields are pulled defensively with .get() and default to None,
    since coverage varies a lot by country/sensor network.
    """
    url = f"{config.OPENAQ_BASE_URL}/locations/{location_id}"
    data = _get_with_retry(url)
    results = data.get("results", [])
    if not results:
        return {"location_id": location_id, "name": None, "city": None, "country": None}

    loc = results[0]
    country = loc.get("country", {}) or {}
    return {
        "location_id": location_id,
        "name": loc.get("name"),
        "city": loc.get("locality"),  # v3 uses "locality" rather than "city"
        "country": country.get("code") or country.get("name"),
    }


def fetch_location_metadata_bulk(location_ids: list[int]) -> dict[int, dict]:
    """
    Resolve metadata for many locations, caching each lookup once.

    A naive per-row lookup would mean one API call per reading — this
    dedupes by location_id first so a location with many readings only
    gets looked up once per run.
    """
    unique_ids = sorted(set(location_ids))
    metadata: dict[int, dict] = {}
    for loc_id in unique_ids:
        try:
            metadata[loc_id] = fetch_location_metadata(loc_id)
        except RuntimeError as exc:
            logger.warning("Could not resolve metadata for location %s: %s", loc_id, exc)
            metadata[loc_id] = {"location_id": loc_id, "name": None, "city": None, "country": None}
    return metadata
