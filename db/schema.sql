-- Curated table schema.
-- Written for Redshift; for Athena, use this as the basis for a
-- CREATE EXTERNAL TABLE pointing at the curated S3 Parquet prefix instead.

CREATE TABLE IF NOT EXISTS air_quality_curated (
    location_id         BIGINT,
    location_name       VARCHAR(256),
    city                VARCHAR(128),
    country             VARCHAR(8),
    parameter           VARCHAR(32),
    value               FLOAT,
    unit                VARCHAR(16),
    date_utc            TIMESTAMP,
    is_extreme_outlier  BOOLEAN,
    load_date           DATE DEFAULT CURRENT_DATE
)
DISTSTYLE KEY
DISTKEY (location_id)
SORTKEY (date_utc);
