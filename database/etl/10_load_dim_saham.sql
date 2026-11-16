INSERT INTO dwh.dim_stock (ticker, name, sector)
SELECT ticker, name, sector
FROM staging.cfg_stock
ON CONFLICT (ticker) DO UPDATE
  SET name = EXCLUDED.name,
      sector = EXCLUDED.sector;
