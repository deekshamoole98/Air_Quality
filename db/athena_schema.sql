-- Athena external table over the curated Parquet written by the Glue job.
-- This is the version actually run in AWS. (db/schema.sql is the Redshift variant;
-- Redshift's DISTKEY/SORTKEY syntax is not valid in Athena.)
--
-- Replace YOUR_BUCKET_NAME before running.

CREATE EXTERNAL TABLE IF NOT EXISTS air_quality_curated (
    location_id         BIGINT,
    location_name       STRING,
    city                STRING,
    country             STRING,
    parameter           STRING,
    value               DOUBLE,
    unit                STRING,
    date_utc            TIMESTAMP,
    is_extreme_outlier  BOOLEAN
)
PARTITIONED BY (`date` STRING)
STORED AS PARQUET
LOCATION 's3://YOUR_BUCKET_NAME/curated/'
TBLPROPERTIES ('parquet.compression' = 'SNAPPY');

-- Run after every Glue run that creates a new date= folder, or Athena won't see it:
-- MSCK REPAIR TABLE air_quality_curated;
