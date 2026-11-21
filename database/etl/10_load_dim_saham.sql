INSERT INTO dwh.dim_stock (ticker, name, sector)
SELECT
  t.ticker,
  COALESCE(t.company_name, c.name) AS name,
  c.sector
FROM staging.ref_ticker t
LEFT JOIN staging.cfg_stock c ON c.ticker = t.ticker
ON CONFLICT (ticker) DO UPDATE
  SET name = COALESCE(EXCLUDED.name, dwh.dim_stock.name),
      sector = COALESCE(EXCLUDED.sector, dwh.dim_stock.sector);
