INSERT INTO dwh.fact_orderbook (
  date_key, stock_key, capture_time, side, level, price, lot, frequency
)
SELECT DISTINCT ON (TO_CHAR(r.captured_at, 'YYYYMMDD')::INT, s.stock_key, r.side, r.level)
  TO_CHAR(r.captured_at, 'YYYYMMDD')::INT,
  s.stock_key,
  r.captured_at::TIME,
  r.side,
  r.level,
  staging.parse_numeric(r.price_raw)::NUMERIC(14,2),
  staging.parse_numeric(r.lot_raw)::BIGINT,
  staging.parse_numeric(r.freq_raw)::INT
FROM staging.orderbook_raw r
JOIN dwh.dim_date t ON t.date_key = TO_CHAR(r.captured_at, 'YYYYMMDD')::INT
JOIN dwh.dim_stock s ON s.ticker = r.ticker
WHERE r.is_processed = FALSE
  AND staging.parse_numeric(r.price_raw) > 0
ORDER BY TO_CHAR(r.captured_at, 'YYYYMMDD')::INT, s.stock_key, r.side, r.level, r.captured_at DESC
ON CONFLICT (date_key, stock_key, side, level) DO UPDATE
  SET capture_time = EXCLUDED.capture_time,
      price = EXCLUDED.price,
      lot = EXCLUDED.lot,
      frequency = EXCLUDED.frequency;

UPDATE staging.orderbook_raw
SET is_processed = TRUE
WHERE is_processed = FALSE;
