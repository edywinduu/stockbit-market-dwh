INSERT INTO dwh.dim_broker (broker_code)
SELECT DISTINCT broker_code
FROM staging.broksum_raw
WHERE is_processed = FALSE
ON CONFLICT (broker_code) DO NOTHING;
