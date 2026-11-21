-- 1. Load into star-schema DWH fact table
INSERT INTO dwh.fact_broker_summary (
  date_key, stock_key, broker_key,
  buy_lot, buy_value, buy_avg_price,
  sell_lot, sell_value, sell_avg_price,
  net_lot, net_value
)
SELECT
  TO_CHAR(r.trade_date, 'YYYYMMDD')::INT,
  s.stock_key,
  b.broker_key,
  staging.parse_numeric(r.buy_lot_raw)::BIGINT,
  staging.parse_numeric(r.buy_val_raw)::NUMERIC(20,2),
  staging.parse_numeric(r.buy_avg_raw)::NUMERIC(14,2),
  staging.parse_numeric(r.sell_lot_raw)::BIGINT,
  staging.parse_numeric(r.sell_val_raw)::NUMERIC(20,2),
  staging.parse_numeric(r.sell_avg_raw)::NUMERIC(14,2),
  COALESCE(staging.parse_numeric(r.buy_lot_raw)::BIGINT, 0)
    - COALESCE(staging.parse_numeric(r.sell_lot_raw)::BIGINT, 0),
  COALESCE(staging.parse_numeric(r.buy_val_raw)::NUMERIC(20,2), 0)
    - COALESCE(staging.parse_numeric(r.sell_val_raw)::NUMERIC(20,2), 0)
FROM staging.broksum_raw r
JOIN dwh.dim_date t ON t.date_key = TO_CHAR(r.trade_date, 'YYYYMMDD')::INT
JOIN dwh.dim_stock s ON s.ticker = r.ticker
JOIN dwh.dim_broker b ON b.broker_code = r.broker_code
WHERE r.is_processed = FALSE
ON CONFLICT (date_key, stock_key, broker_key) DO UPDATE
  SET buy_lot = EXCLUDED.buy_lot,
      buy_value = EXCLUDED.buy_value,
      buy_avg_price = EXCLUDED.buy_avg_price,
      sell_lot = EXCLUDED.sell_lot,
      sell_value = EXCLUDED.sell_value,
      sell_avg_price = EXCLUDED.sell_avg_price,
      net_lot = EXCLUDED.net_lot,
      net_value = EXCLUDED.net_value;

-- 2. Load into denormalized public.fact_broksum with idempotent upsert
INSERT INTO public.fact_broksum (
  trade_date, ticker, broker_code,
  buy_lot, buy_value, buy_avg_price,
  sell_lot, sell_value, sell_avg_price,
  net_lot, net_value, updated_at
)
SELECT
  r.trade_date,
  r.ticker,
  r.broker_code,
  staging.parse_numeric(r.buy_lot_raw)::BIGINT,
  staging.parse_numeric(r.buy_val_raw)::NUMERIC(20,2),
  staging.parse_numeric(r.buy_avg_raw)::NUMERIC(14,2),
  staging.parse_numeric(r.sell_lot_raw)::BIGINT,
  staging.parse_numeric(r.sell_val_raw)::NUMERIC(20,2),
  staging.parse_numeric(r.sell_avg_raw)::NUMERIC(14,2),
  COALESCE(staging.parse_numeric(r.buy_lot_raw)::BIGINT, 0)
    - COALESCE(staging.parse_numeric(r.sell_lot_raw)::BIGINT, 0),
  COALESCE(staging.parse_numeric(r.buy_val_raw)::NUMERIC(20,2), 0)
    - COALESCE(staging.parse_numeric(r.sell_val_raw)::NUMERIC(20,2), 0),
  NOW()
FROM staging.broksum_raw r
WHERE r.is_processed = FALSE
ON CONFLICT (trade_date, ticker, broker_code) DO UPDATE
  SET buy_lot = EXCLUDED.buy_lot,
      buy_value = EXCLUDED.buy_value,
      buy_avg_price = EXCLUDED.buy_avg_price,
      sell_lot = EXCLUDED.sell_lot,
      sell_value = EXCLUDED.sell_value,
      sell_avg_price = EXCLUDED.sell_avg_price,
      net_lot = EXCLUDED.net_lot,
      net_value = EXCLUDED.net_value,
      updated_at = NOW();

UPDATE staging.broksum_raw
SET is_processed = TRUE
WHERE is_processed = FALSE;
