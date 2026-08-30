# Building the Tableau Dashboard

This covers turning `air_quality_curated_export.csv` (produced by
`scripts/export_for_tableau.py`) into a dashboard in Tableau Desktop
or Tableau Public.

## 1. Get real historical data first

The regular pipeline (`lambda_handler.py`) only pulls the *latest*
snapshot — one reading per station. That's not enough for a trend
chart. Backfill some history first:

```bash
# Find location ids for cities you want to track
python scripts/find_locations.py US "Dallas"
python scripts/find_locations.py US "Los Angeles"

# Add the ids you want to .env, e.g.:
# BACKFILL_LOCATION_IDS=1772963,2954721,8152
# BACKFILL_DAYS=60

python -m ingestion.backfill
python scripts/export_for_tableau.py
```

This produces `air_quality_curated_export.csv` with columns:
`location_id, location_name, city, country, parameter, value, unit,
date_utc, reading_date, week_start, exceeds_who_guideline`

## 2. Connect Tableau to the CSV

1. Open Tableau Desktop → **Connect > Text File** → select `air_quality_curated_export.csv`
2. Confirm `date_utc` is recognized as a Date/Datetime field (Tableau usually gets this right automatically; if not, right-click the field → Change Data Type → Date)
3. Go to Sheet 1

## 3. Build the three core visuals

**A. PM2.5 trend by city (line chart)**
- Drag `reading_date` to Columns, `value` to Rows
- Set `value`'s aggregation to Average (right-click the pill → Measure → Average)
- Drag `city` to Color
- This is your daily-average-by-city view (mirrors `vw_daily_avg_pm25_by_city`)

**B. WHO threshold breach rate (bar chart)**
- Create a calculated field: **Breach Rate %**
  ```
  SUM(IF [exceeds_who_guideline] THEN 1 ELSE 0 END) / COUNT([value]) * 100
  ```
- Drag `city` to Columns, `Breach Rate %` to Rows
- Sort descending — this immediately shows which city has the worst air quality most often

**C. Week-over-week change (line or bar)**
- Drag `week_start` to Columns, `value` (Average) to Rows, `city` to Color
- Optional: add a **Table Calculation** on the `value` pill → Percent Difference, computed along `week_start` — this gives you the WoW % change directly in the tooltip

## 4. Assemble the dashboard

1. **Dashboard > New Dashboard**
2. Drag all three sheets onto the canvas (stack B and C side by side under A, or however reads best)
3. Add a **City filter** (right-click `city` in one sheet → Show Filter), then apply it to all sheets (filter dropdown → Apply to Worksheets > All Using This Data Source)
4. Add a title, e.g. "Air Quality Monitoring: PM2.5 Trends & WHO Threshold Breaches"

## 5. What to write about it in your README / portfolio

Once you can see the actual chart, pull 2–3 concrete takeaways, e.g.:
- Which city breaches the WHO guideline most often, and by how much
- Whether PM2.5 is trending up or down over your backfill window
- Any day-of-week or seasonal pattern visible in the line chart

Those sentences are what turn this from "a chart exists" into an
actual finding — that's the piece an interviewer will ask about.

## 6. Publish (optional but recommended)

Tableau Public lets you publish a live, embeddable dashboard for free —
**File > Save to Tableau Public** — and you can link it directly from
your GitHub README so it's viewable without anyone opening Tableau.
