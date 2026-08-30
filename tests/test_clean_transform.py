import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transform.clean_transform import clean_readings


def _make_record(location_id=1, value=10.0, date_utc="2026-08-27T10:00:00Z", city="Dallas", country="US"):
    return {
        "locationsId": location_id,
        "value": value,
        "datetime": {"utc": date_utc},
        "location_meta": {"name": f"loc-{location_id}", "city": city, "country": country},
    }


def test_filters_sentinel_negative_values():
    records = [_make_record(value=-1.0), _make_record(value=12.5)]
    df = clean_readings(records)
    assert len(df) == 1
    assert df.iloc[0]["value"] == 12.5


def test_deduplicates_same_location_parameter_timestamp():
    records = [_make_record(location_id=5), _make_record(location_id=5)]
    df = clean_readings(records)
    assert len(df) == 1


def test_keeps_distinct_readings():
    records = [
        _make_record(location_id=1, date_utc="2026-08-27T10:00:00Z"),
        _make_record(location_id=1, date_utc="2026-08-27T11:00:00Z"),
        _make_record(location_id=2, date_utc="2026-08-27T10:00:00Z"),
    ]
    df = clean_readings(records)
    assert len(df) == 3


def test_flattens_city_and_country():
    records = [_make_record(city="Dallas", country="US")]
    df = clean_readings(records)
    assert df.iloc[0]["city"] == "Dallas"
    assert df.iloc[0]["country"] == "US"


def test_empty_input_returns_empty_dataframe_with_expected_columns():
    df = clean_readings([])
    assert len(df) == 0
    assert "value" in df.columns
    assert "city" in df.columns


def test_drops_rows_with_unparseable_date():
    records = [_make_record(date_utc="not-a-date"), _make_record(date_utc="2026-08-27T10:00:00Z")]
    df = clean_readings(records)
    assert len(df) == 1


def test_filters_positive_sentinel_values():
    # 9999 is a real sentinel seen in production data — MIN_VALID_VALUE alone
    # (>= 0) doesn't catch it since it's a large positive number, not negative.
    records = [_make_record(value=9999.0), _make_record(value=12.5)]
    df = clean_readings(records)
    assert len(df) == 1
    assert df.iloc[0]["value"] == 12.5


def test_flags_extreme_outliers_without_dropping_them():
    records = [_make_record(location_id=1, value=800.0), _make_record(location_id=2, value=12.5)]
    df = clean_readings(records)
    assert len(df) == 2  # both kept
    outlier_row = df[df["value"] == 800.0].iloc[0]
    assert outlier_row["is_extreme_outlier"] is True or bool(outlier_row["is_extreme_outlier"]) is True
    normal_row = df[df["value"] == 12.5].iloc[0]
    assert bool(normal_row["is_extreme_outlier"]) is False
