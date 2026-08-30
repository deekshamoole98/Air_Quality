import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("OPENAQ_API_KEY", "test-key")

import config
from ingestion import backfill


@patch("ingestion.backfill.write_json")
@patch("ingestion.backfill.fetch_measurements")
@patch("ingestion.backfill.fetch_location_metadata")
def test_backfill_groups_measurements_by_their_own_date(mock_meta, mock_fetch, mock_write):
    mock_meta.return_value = {"name": "Test Station", "city": "Testville", "country": "US"}
    mock_fetch.return_value = [
        {"datetime": {"utc": "2026-08-01T23:00:00Z"}, "value": 5.0, "locationsId": 42, "sensorsId": 1},
        {"datetime": {"utc": "2026-08-02T00:00:00Z"}, "value": 6.0, "locationsId": 42, "sensorsId": 1},
        {"datetime": {"utc": "2026-08-02T01:00:00Z"}, "value": 7.0, "locationsId": 42, "sensorsId": 1},
    ]
    mock_write.return_value = "some/path.json"

    with patch.object(config, "BACKFILL_LOCATION_IDS", [42]):
        written = backfill.run_backfill()

    assert len(written) == 2  # one raw file per distinct date, not per location
    written_keys = [call.args[1] for call in mock_write.call_args_list]
    assert any(k.startswith("date=2026-08-01/") for k in written_keys)
    assert any(k.startswith("date=2026-08-02/") for k in written_keys)


@patch("ingestion.backfill.write_json")
def test_backfill_no_op_when_no_locations_configured(mock_write):
    with patch.object(config, "BACKFILL_LOCATION_IDS", []):
        written = backfill.run_backfill()
    assert written == []
    mock_write.assert_not_called()
