CREATE SCHEMA IF NOT EXISTS staging;

-- 1. Configuration table for stocks to be captured
CREATE TABLE staging.cfg_stock (
  ticker        VARCHAR(10) PRIMARY KEY,
  name          VARCHAR(100),
  sector        VARCHAR(60),
  is_active     BOOLEAN DEFAULT TRUE
);

-- 1b. Persistent authentication token store (synced from host browser session)
CREATE TABLE IF NOT EXISTS staging.cfg_auth (
  provider      VARCHAR(50) PRIMARY KEY,
  auth_header   TEXT NOT NULL,
  updated_at    TIMESTAMP DEFAULT NOW()
);

-- 2. Reference table for market holidays
CREATE TABLE staging.ref_holiday (
  holiday_date  DATE PRIMARY KEY,
  description   VARCHAR(100)
);

-- 3. Pipeline audit and execution log
CREATE TABLE staging.capture_log (
  capture_id    BIGSERIAL PRIMARY KEY,
  capture_type  VARCHAR(20) NOT NULL,           -- orderbook | broksum
  ticker        VARCHAR(10),
  started_at    TIMESTAMP NOT NULL,
  finished_at   TIMESTAMP,
  status        VARCHAR(10) NOT NULL,           -- RUNNING | SUCCESS | FAILED | SKIPPED
  row_count     INT DEFAULT 0,
  error_message TEXT,
  triggered_by  VARCHAR(10) DEFAULT 'SCHEDULER' -- SCHEDULER | MANUAL
);

-- 4. ETL pipeline audit log
CREATE TABLE staging.etl_log (
  etl_id        BIGSERIAL PRIMARY KEY,
  executed_at   TIMESTAMP NOT NULL DEFAULT NOW(),
  status        VARCHAR(10) NOT NULL,           -- SUCCESS | FAILED
  description   TEXT
);

-- 5. Helper function to parse raw numeric strings (e.g. '1,234.56', '1234')
CREATE OR REPLACE FUNCTION staging.parse_numeric(val TEXT)
RETURNS NUMERIC AS $$
BEGIN
  IF val IS NULL OR TRIM(val) = '' THEN
    RETURN NULL;
  END IF;
  -- Hapus koma pemisah ribuan atau spasi jika ada
  RETURN REPLACE(REPLACE(TRIM(val), ',', ''), ' ', '')::NUMERIC;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 6. Raw staging table for orderbook snapshots
CREATE TABLE staging.orderbook_raw (
  id            BIGSERIAL PRIMARY KEY,
  capture_id    BIGINT REFERENCES staging.capture_log(capture_id),
  ticker        VARCHAR(10) NOT NULL,
  captured_at   TIMESTAMP NOT NULL,
  side          CHAR(1) NOT NULL,                 -- B (bid) | O (offer)
  level         SMALLINT NOT NULL,
  price_raw     VARCHAR(30),
  lot_raw       VARCHAR(30),
  freq_raw      VARCHAR(30),
  is_processed  BOOLEAN DEFAULT FALSE
);

-- 7. Raw staging table for broker summary (broksum)
CREATE TABLE staging.broksum_raw (
  id            BIGSERIAL PRIMARY KEY,
  capture_id    BIGINT REFERENCES staging.capture_log(capture_id),
  ticker        VARCHAR(10) NOT NULL,
  trade_date    DATE NOT NULL,
  broker_code   VARCHAR(5) NOT NULL,
  buy_lot_raw   VARCHAR(30),
  buy_val_raw   VARCHAR(30),
  buy_avg_raw   VARCHAR(30),
  sell_lot_raw  VARCHAR(30),
  sell_val_raw  VARCHAR(30),
  sell_avg_raw  VARCHAR(30),
  is_processed  BOOLEAN DEFAULT FALSE,
  UNIQUE (ticker, trade_date, broker_code)
);
