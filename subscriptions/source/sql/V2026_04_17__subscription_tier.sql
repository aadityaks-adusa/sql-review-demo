-- Migration: add subscription tier + widen plan_code column
-- ⚠️  This file is intentionally seeded with DBA_REVIEW issues.

-- D9: CREATE TABLE without IF NOT EXISTS — Flyway retry fails
CREATE TABLE subscriptions.subscription_tier (
    tier_id             SERIAL PRIMARY KEY,
    tier_nm             VARCHAR(50)  NOT NULL,
    monthly_price_amt   NUMERIC(10,2) NOT NULL,
    audt_cr_dt_tm       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id          VARCHAR(100) NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id         VARCHAR(100) NOT NULL DEFAULT CURRENT_USER
);

-- D1: ALTER COLUMN TYPE — full row rewrite + exclusive lock
ALTER TABLE subscriptions.subscription
    ALTER COLUMN plan_cd TYPE VARCHAR(100) USING plan_cd::VARCHAR(100);

-- D10: CREATE INDEX without IF NOT EXISTS — Flyway retry fails
CREATE INDEX idx_subscription_tier_nm ON subscriptions.subscription_tier (tier_nm);
