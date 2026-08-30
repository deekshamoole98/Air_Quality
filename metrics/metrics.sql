-- Metrics layer: reusable views on top of air_quality_curated.
-- These are the metrics the dashboard (Step 7) is built on, defined
-- once here rather than recomputed ad hoc in each chart.

-- 1. Daily average PM2.5 by city
-- Excludes rows flagged is_extreme_outlier so a single miscalibrated
-- sensor spike doesn't blow out a city's daily average.
CREATE OR REPLACE VIEW vw_daily_avg_pm25_by_city AS
SELECT
    city,
    country,
    DATE(date_utc)      AS reading_date,
    AVG(value)           AS avg_pm25,
    COUNT(*)              AS reading_count
FROM air_quality_curated
WHERE parameter = 'pm25'
  AND city IS NOT NULL
  AND NOT is_extreme_outlier
GROUP BY city, country, DATE(date_utc);


-- 2. % of readings exceeding the WHO 24-hour PM2.5 guideline (15 µg/m³)
CREATE OR REPLACE VIEW vw_who_threshold_breach_rate AS
SELECT
    city,
    country,
    DATE(date_utc)                                         AS reading_date,
    COUNT(*)                                                 AS total_readings,
    SUM(CASE WHEN value > 15 THEN 1 ELSE 0 END)              AS breaches,
    ROUND(
        100.0 * SUM(CASE WHEN value > 15 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        1
    )                                                          AS breach_pct
FROM air_quality_curated
WHERE parameter = 'pm25'
  AND city IS NOT NULL
  AND NOT is_extreme_outlier
GROUP BY city, country, DATE(date_utc);


-- 3. Week-over-week trend in average PM2.5 by city
CREATE OR REPLACE VIEW vw_wow_pm25_trend AS
WITH weekly AS (
    SELECT
        city,
        country,
        DATE_TRUNC('week', date_utc)  AS week_start,
        AVG(value)                     AS avg_pm25
    FROM air_quality_curated
    WHERE parameter = 'pm25'
      AND city IS NOT NULL
      AND NOT is_extreme_outlier
    GROUP BY city, country, DATE_TRUNC('week', date_utc)
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
FROM weekly
ORDER BY city, week_start;


-- 4. Flagged extreme outliers, for review — not real WHO breaches, likely
-- a miscalibrated sensor. Kept out of the metrics above, surfaced here.
CREATE OR REPLACE VIEW vw_flagged_outliers AS
SELECT
    location_id,
    location_name,
    city,
    country,
    value,
    unit,
    date_utc
FROM air_quality_curated
WHERE parameter = 'pm25'
  AND is_extreme_outlier
ORDER BY date_utc DESC;
