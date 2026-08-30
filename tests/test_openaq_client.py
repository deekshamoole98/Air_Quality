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


@patch("storage.storage.write_json")
@patch("storage.storage.read_json")
@patch("ingestion.openaq_client.fetch_location_metadata")
def test_fetch_location_metadata_bulk_dedupes_ids(mock_fetch_one, mock_read_json, mock_write_json):
    mock_read_json.side_effect = FileNotFoundError()  # no cache yet
    mock_fetch_one.return_value = {"location_id": 1, "name": "x", "city": "Dallas", "country": "US"}
    result = openaq_client.fetch_location_metadata_bulk([1, 1, 1, 2])
    assert mock_fetch_one.call_count == 2  # only unique ids looked up
    assert set(result.keys()) == {1, 2}


@patch("storage.storage.write_json")
@patch("storage.storage.read_json")
@patch("ingestion.openaq_client.fetch_location_metadata")
def test_fetch_location_metadata_bulk_skips_already_cached_ids(mock_fetch_one, mock_read_json, mock_write_json):
    mock_read_json.return_value = {"1": {"location_id": 1, "name": "Cached", "city": "Dallas", "country": "US"}}
    mock_fetch_one.return_value = {"location_id": 2, "name": "New", "city": "Austin", "country": "US"}

    result = openaq_client.fetch_location_metadata_bulk([1, 2])

    mock_fetch_one.assert_called_once_with(2)  # id 1 came from cache, never re-fetched
    assert result[1]["name"] == "Cached"
    assert result[2]["name"] == "New"


@patch("storage.storage.write_json")
@patch("storage.storage.read_json")
@patch("ingestion.openaq_client.fetch_location_metadata")
def test_fetch_location_metadata_bulk_does_not_persist_transient_failures(mock_fetch_one, mock_read_json, mock_write_json):
    mock_read_json.side_effect = FileNotFoundError()
    mock_fetch_one.side_effect = RuntimeError("rate limited")

    result = openaq_client.fetch_location_metadata_bulk([1])

    assert result[1]["city"] is None
    # A transient failure shouldn't get written to the cache — otherwise a
    # rate-limited run permanently poisons a location as "no metadata".
    written_cache = mock_write_json.call_args.args[2] if mock_write_json.called else {}
    assert "1" not in written_cache


@patch("ingestion.openaq_client._SESSION.get")
def test_resolve_sensor_id_matches_by_parameter(mock_get):
    mock_get.return_value = _mock_response(
        {
            "results": [
                {
                    "sensors": [
                        {"id": 111, "parameter": {"id": 1, "name": "pm10"}},
                        {"id": 222, "parameter": {"id": 2, "name": "pm25"}},
                    ]
                }
            ]
        }
    )
    assert openaq_client._resolve_sensor_id(location_id=42, parameter_id=2) == 222


@patch("ingestion.openaq_client._SESSION.get")
def test_resolve_sensor_id_returns_none_when_no_matching_sensor(mock_get):
    mock_get.return_value = _mock_response(
        {"results": [{"sensors": [{"id": 111, "parameter": {"id": 1, "name": "pm10"}}]}]}
    )
    assert openaq_client._resolve_sensor_id(location_id=42, parameter_id=2) is None


@patch("ingestion.openaq_client._SESSION.get")
def test_fetch_measurements_shapes_records_like_latest_readings(mock_get):
    location_response = _mock_response(
        {"results": [{"sensors": [{"id": 222, "parameter": {"id": 2, "name": "pm25"}}]}]}
    )
    measurements_response = _mock_response(
        {
            "results": [
                {
                    "value": 9.0,
                    "period": {"datetimeFrom": {"utc": "2026-08-01T00:00:00Z"}},
                }
            ]
        }
    )
    mock_get.side_effect = [location_response, measurements_response]

    results = openaq_client.fetch_measurements(42, "2026-08-01", "2026-08-02", parameter_id=2)

    assert results == [
        {
            "datetime": {"utc": "2026-08-01T00:00:00Z"},
            "value": 9.0,
            "locationsId": 42,
            "sensorsId": 222,
        }
    ]


@patch("ingestion.openaq_client._resolve_sensor_id")
def test_fetch_measurements_returns_empty_when_no_sensor_for_parameter(mock_resolve):
    mock_resolve.return_value = None
    assert openaq_client.fetch_measurements(42, "2026-08-01", "2026-08-02", parameter_id=2) == []


@patch("ingestion.openaq_client._SESSION.get")
def test_search_locations_passes_country_and_parameter_filters(mock_get):
    mock_get.return_value = _mock_response({"results": [{"id": 1, "name": "Test"}]})
    results = openaq_client.search_locations("US", parameter_id=2, limit=50)
    assert results == [{"id": 1, "name": "Test"}]
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"iso": "US", "parameters_id": 2, "limit": 50}
