-- ============================================================================
-- 03_seed.sql
-- Initial Seed Data for Staging and Data Warehouse (DWH)
-- ============================================================================

-- 1. Seed Core Stocks into Staging & DWH
INSERT INTO staging.cfg_stock (ticker, name, sector, is_active) VALUES
('BBCA', 'Bank Central Asia Tbk.', 'Financials', TRUE),
('BBRI', 'Bank Rakyat Indonesia Tbk.', 'Financials', TRUE),
('BMRI', 'Bank Mandiri (Persero) Tbk.', 'Financials', TRUE),
('TLKM', 'Telkom Indonesia (Persero) Tbk.', 'Telecommunication', TRUE),
('ASII', 'Astra International Tbk.', 'Industrials', TRUE)
ON CONFLICT (ticker) DO NOTHING;

INSERT INTO dwh.dim_stock (ticker, name, sector)
SELECT ticker, name, sector FROM staging.cfg_stock
ON CONFLICT (ticker) DO NOTHING;

-- 2. Auto-generate Date Dimension for Full Years 2026-2027
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
FROM generate_series('2026-01-01'::DATE, '2027-12-31'::DATE, '1 day'::INTERVAL) AS d
ON CONFLICT (date_key) DO NOTHING;

-- 3. Seed Reference Holidays (2026-2027) & Synchronize Trading Days
INSERT INTO staging.ref_holiday (holiday_date, description) VALUES
('2026-01-01', 'New Year 2026'),
('2026-01-16', 'Isra Miraj'),
('2026-02-17', 'Chinese New Year 2577'),
('2026-03-20', 'Hari Raya Nyepi'),
('2026-03-21', 'Eid al-Fitr 1447 H'),
('2026-03-22', 'Eid al-Fitr Holiday'),
('2026-04-03', 'Good Friday'),
('2026-05-01', 'International Labor Day'),
('2026-05-14', 'Ascension of Jesus Christ'),
('2026-05-31', 'Waisak Day'),
('2026-06-01', 'Pancasila Day'),
('2026-06-16', 'Eid al-Adha 1447 H'),
('2026-07-07', 'Islamic New Year 1448 H'),
('2026-08-17', 'Indonesian Independence Day'),
('2026-09-15', 'Prophet Muhammad Birthday'),
('2026-12-25', 'Christmas Day'),
('2027-01-01', 'Tahun Baru 2027 Masehi'),
('2027-01-05', 'Isra Mikraj Nabi Muhammad S.A.W. 1448 Hijriah'),
('2027-02-05', 'Cuti Bersama Tahun Baru Imlek 2578 Kongzili'),
('2027-03-08', 'Hari Suci Nyepi (Tahun Baru Saka 1949)'),
('2027-03-09', 'Cuti Bersama Idul Fitri 1448 Hijriah'),
('2027-03-10', 'Idul Fitri 1448 Hijriah'),
('2027-03-11', 'Idul Fitri 1448 Hijriah'),
('2027-03-12', 'Cuti Bersama Idul Fitri 1448 Hijriah'),
('2027-03-15', 'Cuti Bersama Idul Fitri 1448 Hijriah'),
('2027-03-25', 'Cuti Bersama Wafat Yesus Kristus'),
('2027-03-26', 'Wafat Yesus Kristus'),
('2027-05-06', 'Kenaikan Yesus Kristus'),
('2027-05-17', 'Idul Adha 1448 Hijriah'),
('2027-05-18', 'Cuti Bersama Idul Adha 1448 Hijriah'),
('2027-05-19', 'Cuti Bersama Hari Raya Waisak 2571 BE'),
('2027-05-20', 'Hari Raya Waisak 2571 BE'),
('2027-06-01', 'Hari Lahir Pancasila'),
('2027-08-17', 'Proklamasi Kemerdekaan'),
('2027-12-24', 'Cuti Bersama Kelahiran Yesus Kristus'),
('2027-12-31', 'Libur Bursa')
ON CONFLICT (holiday_date) DO NOTHING;

-- Update non-trading days in dim_date according to official market holidays
UPDATE dwh.dim_date d
SET is_trading_day = FALSE
FROM staging.ref_holiday h
WHERE d.calendar_date = h.holiday_date;

-- 4. Seed Initial Broker Dimension
INSERT INTO dwh.dim_broker (broker_code, broker_name, broker_type) VALUES
('YP', 'Mirae Asset Sekuritas Indonesia', 'FOREIGN'),
('PD', 'Indo Premier Sekuritas', 'DOMESTIC'),
('CC', 'Mandiri Sekuritas', 'STATE_OWNED'),
('AK', 'UBS Sekuritas Indonesia', 'FOREIGN'),
('BK', 'J.P. Morgan Sekuritas Indonesia', 'FOREIGN'),
('ZP', 'Maybank Sekuritas Indonesia', 'FOREIGN'),
('KZ', 'CLSA Sekuritas Indonesia', 'FOREIGN'),
('RX', 'Macquarie Sekuritas Indonesia', 'FOREIGN'),
('XL', 'Stockbit Sekuritas Digital', 'DOMESTIC'),
('XC', 'Ajaib Sekuritas Asia', 'DOMESTIC'),
('SQ', 'BCA Sekuritas', 'DOMESTIC'),
('NI', 'BNI Sekuritas', 'STATE_OWNED'),
('OD', 'BRI Danareksa Sekuritas', 'STATE_OWNED'),
('DX', 'Bahana Sekuritas', 'STATE_OWNED'),
('TP', 'OCBC Sekuritas Indonesia', 'FOREIGN'),
('YU', 'CGS International Sekuritas Indonesia', 'FOREIGN'),
('MG', 'Semesta Indovest Sekuritas', 'DOMESTIC'),
('BB', 'Verdhana Sekuritas Indonesia', 'DOMESTIC'),
('GR', 'Panin Sekuritas Tbk.', 'DOMESTIC'),
('KK', 'Phillip Sekuritas Indonesia', 'FOREIGN'),
('AZ', 'Sucor Sekuritas', 'DOMESTIC'),
('DH', 'Sinarmas Sekuritas', 'DOMESTIC'),
('LG', 'Trimegah Sekuritas Indonesia Tbk.', 'DOMESTIC')
ON CONFLICT (broker_code) DO UPDATE
  SET broker_name = EXCLUDED.broker_name,
      broker_type = EXCLUDED.broker_type;
