CREATE SCHEMA IF NOT EXISTS staging;

-- 1. Master active IDX ticker table (~950+ tickers)
CREATE TABLE IF NOT EXISTS staging.ref_ticker (
  ticker        VARCHAR(10) PRIMARY KEY,
  company_name  TEXT,
  is_active     BOOLEAN DEFAULT TRUE,
  updated_at    TIMESTAMP DEFAULT NOW()
);

-- Seed existing configured tickers if staging.cfg_stock exists
DO $$
BEGIN
  IF to_regclass('staging.cfg_stock') IS NOT NULL THEN
    INSERT INTO staging.ref_ticker (ticker, company_name, is_active, updated_at)
    SELECT ticker, name, COALESCE(is_active, TRUE), NOW()
    FROM staging.cfg_stock
    ON CONFLICT (ticker) DO NOTHING;
  END IF;
END $$;

-- 2. Extend staging.capture_log for resumable (job_type, ticker, trade_date) checkpointing
ALTER TABLE staging.capture_log
  ADD COLUMN IF NOT EXISTS job_type   VARCHAR(20),
  ADD COLUMN IF NOT EXISTS trade_date DATE,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

UPDATE staging.capture_log
SET job_type = COALESCE(job_type, capture_type),
    updated_at = COALESCE(updated_at, finished_at, started_at, NOW())
WHERE job_type IS NULL OR updated_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_capture_log_checkpoint
  ON staging.capture_log (job_type, ticker, trade_date);

-- 3. Ensure staging.broksum_raw tracks updated_at and enforces idempotent unique key
ALTER TABLE staging.broksum_raw
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS uq_broksum_raw_ticker_date_broker
  ON staging.broksum_raw (ticker, trade_date, broker_code);

-- 4. Denormalized public fact table for idempotent Broksum ingestion/analytics
CREATE TABLE IF NOT EXISTS public.fact_broksum (
  id             BIGSERIAL PRIMARY KEY,
  trade_date     DATE NOT NULL,
  ticker         VARCHAR(10) NOT NULL,
  broker_code    VARCHAR(5) NOT NULL,
  buy_lot        BIGINT,
  buy_value      NUMERIC(20,2),
  buy_avg_price  NUMERIC(14,2),
  sell_lot       BIGINT,
  sell_value     NUMERIC(20,2),
  sell_avg_price NUMERIC(14,2),
  net_lot        BIGINT,
  net_value      NUMERIC(20,2),
  updated_at     TIMESTAMP DEFAULT NOW(),
  CONSTRAINT uq_public_fact_broksum UNIQUE (trade_date, ticker, broker_code)
);
