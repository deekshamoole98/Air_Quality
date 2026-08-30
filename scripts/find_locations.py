"""
Helper for finding OpenAQ location ids to put in BACKFILL_LOCATION_IDS.

The /locations endpoint doesn't support a free-text city search, so this
filters by country code (ISO 3166-1 alpha-2) and an optional substring
match on name/locality, client-side, after fetching.

Usage:
    python -m scripts.find_locations --country US --search "san francisco"
    python -m scripts.find_locations --country KR
"""
from __future__ import annotations

import argparse

from ingestion.openaq_client import search_locations as _search_locations


def find_locations(country: str, search: str | None = None, limit: int = 100) -> list[dict]:
    results = _search_locations(country, limit=limit)
    if search:
        needle = search.lower()
        results = [
            r for r in results
            if needle in (r.get("name") or "").lower() or needle in (r.get("locality") or "").lower()
        ]
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True, help="ISO 3166-1 alpha-2 country code, e.g. US")
    parser.add_argument("--search", help="Substring to match against location name/locality")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    locations = find_locations(args.country, args.search, args.limit)
    if not locations:
        print("No matching locations found.")
        return

    print(f"{'id':>10}  {'name':<35} {'locality':<25} country")
    for loc in locations:
        country_code = (loc.get("country") or {}).get("code", "")
        print(f"{loc['id']:>10}  {(loc.get('name') or '')[:35]:<35} {(loc.get('locality') or '')[:25]:<25} {country_code}")


if __name__ == "__main__":
    main()
