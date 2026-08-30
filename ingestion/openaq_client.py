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
    return {"X-API-Key": config.get_openaq_api_key()}


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


def search_locations(country: str, parameter_id: int | None = None, limit: int = 100) -> list[dict]:
    """
    List locations for a country (ISO 3166-1 alpha-2 code) that report a
    given parameter. Used by scripts/find_locations.py to find ids for
    BACKFILL_LOCATION_IDS — the API has no free-text city search.
    """
    parameter_id = parameter_id or config.OPENAQ_PARAMETER_ID
    url = f"{config.OPENAQ_BASE_URL}/locations"
    data = _get_with_retry(url, params={"iso": country, "parameters_id": parameter_id, "limit": limit})
    return data.get("results", [])


def _resolve_sensor_id(location_id: int, parameter_id: int) -> int | None:
    """
    A location can host sensors for several parameters — find the one for
    the parameter we care about. Confirmed against the live API: location
    detail responses include a `sensors` list, each tagged with its own
    `parameter.id`; there's no direct "get sensor for parameter X" lookup.
    """
    url = f"{config.OPENAQ_BASE_URL}/locations/{location_id}"
    data = _get_with_retry(url)
    results = data.get("results", [])
    if not results:
        return None
    for sensor in results[0].get("sensors", []):
        if sensor.get("parameter", {}).get("id") == parameter_id:
            return sensor.get("id")
    return None


def fetch_measurements(
    location_id: int,
    datetime_from: str,
    datetime_to: str,
    parameter_id: int | None = None,
    limit: int = 1000,
) -> list[dict]:
    """
    Fetch historical measurements for a single location over a date range,
    for backfilling trend history (`/parameters/{id}/latest`, used by
    fetch_latest_readings, only ever returns the single most recent value
    per station — not enough for a trend chart).

    NOTE: this hits `/sensors/{sensor_id}/measurements`, not
    `/locations/{id}/measurements` (that endpoint 404s on the live v3 API
    despite the "locations" prefix everywhere else). The date-range params
    are also `datetime_from`/`datetime_to`, not `date_from`/`date_to` —
    the latter are silently ignored rather than erroring, which is easy to
    miss without checking a real response. Both were verified directly
    against the API before writing this, not assumed from docs.

    Returns records shaped like fetch_latest_readings's output (`datetime`,
    `value`, `locationsId`, `sensorsId`) so they flow through the same
    transform code with no special-casing.
    """
    parameter_id = parameter_id or config.OPENAQ_PARAMETER_ID
    sensor_id = _resolve_sensor_id(location_id, parameter_id)
    if sensor_id is None:
        logger.warning(
            "Location %s has no sensor for parameter_id=%s; skipping", location_id, parameter_id
        )
        return []

    url = f"{config.OPENAQ_BASE_URL}/sensors/{sensor_id}/measurements"
    results: list[dict] = []
    page = 1
    page_size = min(limit, 1000)

    while len(results) < limit:
        data = _get_with_retry(
            url,
            params={
                "datetime_from": datetime_from,
                "datetime_to": datetime_to,
                "limit": page_size,
                "page": page,
            },
        )
        batch = data.get("results", [])
        if not batch:
            break
        for record in batch:
            period = record.get("period", {}) or {}
            results.append(
                {
                    "datetime": period.get("datetimeFrom", {}),
                    "value": record.get("value"),
                    "locationsId": location_id,
                    "sensorsId": sensor_id,
                }
            )
        if len(batch) < page_size:
            break
        page += 1

    return results[:limit]


_METADATA_CACHE_PREFIX = "cache"
_METADATA_CACHE_KEY = "location_metadata.json"


def _load_metadata_cache() -> dict[int, dict]:
    from storage.storage import read_json

    try:
        raw = read_json(_METADATA_CACHE_PREFIX, _METADATA_CACHE_KEY)
        return {int(k): v for k, v in raw.items()}
    except Exception:
        # First run, or backend-specific "not found" (FileNotFoundError locally,
        # a botocore ClientError on S3) — either way, start from an empty cache.
        return {}


def fetch_location_metadata_bulk(location_ids: list[int]) -> dict[int, dict]:
    """
    Resolve metadata for many locations, persisting results to a cache so
    repeat runs don't re-look-up locations they've already resolved —
    city/country/name for a given station essentially never changes, and
    a run touching ~1000 unique locations otherwise means ~1000 sequential
    API calls (OpenAQ rate-limits per key, so this can't be parallelized
    away — caching is the only thing that actually helps).
    """
    from storage.storage import write_json

    unique_ids = sorted(set(location_ids))
    cache = _load_metadata_cache()
    metadata: dict[int, dict] = {}
    newly_resolved = False

    for loc_id in unique_ids:
        if loc_id in cache:
            metadata[loc_id] = cache[loc_id]
            continue
        try:
            metadata[loc_id] = fetch_location_metadata(loc_id)
        except RuntimeError as exc:
            # Transient failure (rate limit exhausted retries, network error) —
            # don't cache it, so the next run retries instead of being stuck
            # with a permanent null. A genuine "no metadata for this location"
            # result (empty `results`) doesn't raise, so it's cached below as normal.
            logger.warning("Could not resolve metadata for location %s: %s", loc_id, exc)
            metadata[loc_id] = {"location_id": loc_id, "name": None, "city": None, "country": None}
            continue
        cache[loc_id] = metadata[loc_id]
        newly_resolved = True

    if newly_resolved:
        write_json(_METADATA_CACHE_PREFIX, _METADATA_CACHE_KEY, {str(k): v for k, v in cache.items()})

    return metadata
