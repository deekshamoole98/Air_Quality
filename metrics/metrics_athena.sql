-- Metric views for Athena (Presto/Trino SQL). These are the views the QuickSight
-- datasets were built on. Run each statement separately in the Athena editor.
--
-- Notes:
--  * Stations with a NULL or blank city are excluded (many OpenAQ stations have none).
--  * OpenAQ's /latest endpoint returns each station's most recent reading, which is
--    often months or years old, so the daily and breach views keep the last 7 days only.
--  * Flagged outliers (is_extreme_outlier) are NOT excluded here. To exclude them, add
--    AND NOT is_extreme_outlier to each WHERE clause.

CREATE OR REPLACE VIEW vw_daily_avg_pm25_by_city AS
SELECT
    city,
    country,
    CAST(date_utc AS DATE)  AS reading_date,
    AVG(value)              AS avg_pm25,
    COUNT(*)                AS reading_count
FROM air_quality_curated
WHERE parameter = 'pm25'
  AND city IS NOT NULL
  AND TRIM(city) <> ''
  AND CAST(date_utc AS DATE) >= current_date - INTERVAL '7' DAY
GROUP BY city, country, CAST(date_utc AS DATE);


CREATE OR REPLACE VIEW vw_who_threshold_breach_rate AS
SELECT
    city,
    country,
    CAST(date_utc AS DATE)                                  AS reading_date,
    COUNT(*)                                                AS total_readings,
    SUM(CASE WHEN value > 15 THEN 1 ELSE 0 END)             AS breaches,
    ROUND(
        100.0 * SUM(CASE WHEN value > 15 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        1
    )                                                       AS breach_pct
FROM air_quality_curated
WHERE parameter = 'pm25'
  AND city IS NOT NULL
  AND TRIM(city) <> ''
  AND CAST(date_utc AS DATE) >= current_date - INTERVAL '7' DAY
GROUP BY city, country, CAST(date_utc AS DATE);


-- No date window here: week-over-week needs several weeks of history to compare.
CREATE OR REPLACE VIEW vw_wow_pm25_trend AS
WITH weekly AS (
    SELECT
        city,
        country,
        date_trunc('week', date_utc)  AS week_start,
        AVG(value)                    AS avg_pm25
    FROM air_quality_curated
    WHERE parameter = 'pm25'
      AND city IS NOT NULL
      AND TRIM(city) <> ''
    GROUP BY city, country, date_trunc('week', date_utc)
)
SELECT
    city,
    country,
    week_start,
    avg_pm25,
    LAG(avg_pm25) OVER (PARTITION BY city ORDER BY week_start) AS prev_week_avg_pm25,
    ROUND(
        100.0 * (avg_pm25 - LAG(avg_pm25) OVER (PARTITION BY city ORDER BY week_start))
        / NULLIF(LAG(avg_pm25) OVER (PARTITION BY city ORDER BY week_start), 0),
        1
    ) AS pct_change_wow
FROM weekly;
