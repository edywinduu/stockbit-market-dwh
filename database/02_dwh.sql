CREATE SCHEMA IF NOT EXISTS dwh;

-- 1. Date dimension table
CREATE TABLE dwh.dim_date (
  date_key        INT PRIMARY KEY,                 -- Format: YYYYMMDD (e.g., 20261113)
  calendar_date   DATE UNIQUE NOT NULL,
  day_name        VARCHAR(10),
  month_number    SMALLINT,
  month_name      VARCHAR(15),
  quarter         SMALLINT,
  year            SMALLINT,
  is_trading_day  BOOLEAN
);

-- 2. Stock/Equity dimension table
CREATE TABLE dwh.dim_stock (
  stock_key       SERIAL PRIMARY KEY,
  ticker          VARCHAR(10) UNIQUE NOT NULL,
  name            VARCHAR(100),
  sector          VARCHAR(60)
);

-- 3. Broker/Securities firm dimension table
CREATE TABLE dwh.dim_broker (
  broker_key      SERIAL PRIMARY KEY,
  broker_code     VARCHAR(5) UNIQUE NOT NULL,
  broker_name     VARCHAR(100),
  broker_type     VARCHAR(20)                      -- FOREIGN | DOMESTIC | STATE_OWNED | UNKNOWN
);

-- 4. Fact table for daily broker summary
CREATE TABLE dwh.fact_broker_summary (
  date_key        INT REFERENCES dwh.dim_date(date_key),
  stock_key       INT REFERENCES dwh.dim_stock(stock_key),
  broker_key      INT REFERENCES dwh.dim_broker(broker_key),
  buy_lot         BIGINT,
  buy_value       NUMERIC(20,2),
  buy_avg_price   NUMERIC(14,2),
  sell_lot        BIGINT,
  sell_value      NUMERIC(20,2),
  sell_avg_price  NUMERIC(14,2),
  net_lot         BIGINT,
  net_value       NUMERIC(20,2),
  PRIMARY KEY (date_key, stock_key, broker_key)
);

-- 5. Fact table for orderbook snapshots
CREATE TABLE dwh.fact_orderbook (
  date_key        INT REFERENCES dwh.dim_date(date_key),
  stock_key       INT REFERENCES dwh.dim_stock(stock_key),
  capture_time    TIME,
  side            CHAR(1),                         -- B (bid) | O (offer)
  level           SMALLINT,
  price           NUMERIC(14,2),
  lot             BIGINT,
  frequency       INT,
  PRIMARY KEY (date_key, stock_key, side, level)
);

-- 6. Summary analytical view for orderbook metrics
CREATE VIEW dwh.v_orderbook_summary AS
SELECT 
  date_key, 
  stock_key,
  SUM(lot) FILTER (WHERE side = 'B') AS total_bid_lot,
  SUM(lot) FILTER (WHERE side = 'O') AS total_offer_lot,
  MIN(price) FILTER (WHERE side = 'O' AND level = 1)
    - MAX(price) FILTER (WHERE side = 'B' AND level = 1) AS spread
FROM dwh.fact_orderbook 
GROUP BY date_key, stock_key;
