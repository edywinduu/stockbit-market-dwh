CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.cfg_auth (
  provider    VARCHAR(50) PRIMARY KEY,
  auth_header TEXT NOT NULL,
  updated_at  TIMESTAMP DEFAULT NOW()
);
