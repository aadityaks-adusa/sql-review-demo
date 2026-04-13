-- V1.0.1__add_discount_feature.sql
-- Adds discount_pct column to cpt_order and indexes for reporting
--
-- ⚠️ THIS FILE IS INTENTIONALLY BROKEN FOR THE DEMO
-- It contains two real patterns that the scanner should catch:
--
--   1. ADD COLUMN without IF NOT EXISTS  → HARD_BLOCK (Tier 1)
--      Real incident: OCDOMAIN-15294 — Flyway failed on retry because this guard was missing
--
--   2. CREATE INDEX without IF NOT EXISTS → DBA_REVIEW (Tier 2)
--      Missing idempotency guard — index creation fails if migration runs twice

-- ❌ Issue 1: Missing IF NOT EXISTS on ADD COLUMN
--    Flyway will throw "column already exists" on any retry after partial failure
ALTER TABLE orders.cpt_order ADD COLUMN discount_pct NUMERIC(5,2);

-- ❌ Issue 2: CREATE INDEX without IF NOT EXISTS
--    Will fail if this migration is re-run (e.g. after a Flyway repair)
CREATE INDEX idx_cpt_order_discount ON orders.cpt_order(discount_pct);
