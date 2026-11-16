-- Ensure dwh.dim_date covers through at least 2027-12-31 or the latest year in staging.ref_holiday
INSERT INTO dwh.dim_date (
  date_key, calendar_date, day_name, month_number, month_name, quarter, year, is_trading_day
)
SELECT
  TO_CHAR(d, 'YYYYMMDD')::INT AS date_key,
  d::DATE AS calendar_date,
  TRIM(TO_CHAR(d, 'Day')) AS day_name,
  EXTRACT(MONTH FROM d)::SMALLINT AS month_number,
  TRIM(TO_CHAR(d, 'Month')) AS month_name,
  EXTRACT(QUARTER FROM d)::SMALLINT AS quarter,
  EXTRACT(YEAR FROM d)::SMALLINT AS year,
  CASE WHEN EXTRACT(ISODOW FROM d) IN (6, 7) THEN FALSE ELSE TRUE END AS is_trading_day
FROM generate_series(
  DATE '2026-01-01',
  GREATEST(
    DATE '2027-12-31',
    MAKE_DATE(
      GREATEST(
        EXTRACT(YEAR FROM CURRENT_DATE)::INT,
        COALESCE((SELECT EXTRACT(YEAR FROM MAX(holiday_date))::INT FROM staging.ref_holiday), 2027)
      ),
      12,
      31
    )
  ),
  INTERVAL '1 day'
) AS d
ON CONFLICT (date_key) DO NOTHING;

-- Synchronize is_trading_day against weekends and staging.ref_holiday
UPDATE dwh.dim_date d
SET is_trading_day = CASE
  WHEN EXTRACT(ISODOW FROM d.calendar_date) IN (6, 7) THEN FALSE
  WHEN EXISTS (
    SELECT 1 FROM staging.ref_holiday h WHERE h.holiday_date = d.calendar_date
  ) THEN FALSE
  ELSE TRUE
END;
