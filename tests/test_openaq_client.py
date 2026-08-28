import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Required env vars must exist before config.py is imported anywhere.
os.environ.setdefault("OPENAQ_API_KEY", "test-key")

from ingestion import openaq_client


def _mock_response(json_data, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status.side_effect = None
    return mock


@patch("ingestion.openaq_client._SESSION.get")
def test_fetch_latest_readings_single_page(mock_get):
    mock_get.return_value = _mock_response({"results": [{"locationsId": 1, "value": 10.0}]})
    results = openaq_client.fetch_latest_readings(limit=10)
    assert len(results) == 1
    assert results[0]["locationsId"] == 1


@patch("ingestion.openaq_client._SESSION.get")
def test_fetch_latest_readings_paginates(mock_get):
    page1 = _mock_response({"results": [{"locationsId": i, "value": 1.0} for i in range(1000)]})
    page2 = _mock_response({"results": [{"locationsId": 1001, "value": 2.0}]})
    mock_get.side_effect = [page1, page2]
    results = openaq_client.fetch_latest_readings(limit=1500)
    assert len(results) == 1001


@patch("ingestion.openaq_client._SESSION.get")
def test_fetch_location_metadata_maps_locality_to_city(mock_get):
    mock_get.return_value = _mock_response(
        {"results": [{"name": "Test Station", "locality": "Dallas", "country": {"code": "US"}}]}
    )
    meta = openaq_client.fetch_location_metadata(42)
    assert meta["city"] == "Dallas"
    assert meta["country"] == "US"


@patch("ingestion.openaq_client._SESSION.get")
def test_fetch_location_metadata_handles_missing_location(mock_get):
    mock_get.return_value = _mock_response({"results": []})
    meta = openaq_client.fetch_location_metadata(999)
    assert meta["city"] is None
    assert meta["country"] is None


@patch("ingestion.openaq_client.fetch_location_metadata")
def test_fetch_location_metadata_bulk_dedupes_ids(mock_fetch_one):
    mock_fetch_one.return_value = {"location_id": 1, "name": "x", "city": "Dallas", "country": "US"}
    result = openaq_client.fetch_location_metadata_bulk([1, 1, 1, 2])
    assert mock_fetch_one.call_count == 2  # only unique ids looked up
    assert set(result.keys()) == {1, 2}
