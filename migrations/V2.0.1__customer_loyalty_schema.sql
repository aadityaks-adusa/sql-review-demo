-- V2.0.1__customer_loyalty_schema.sql
-- JIRA: OCDOMAIN-20115
-- Extends cpt_order for loyalty program + adds loyalty_tier lookup

-- DBA_REVIEW #1: ALTER COLUMN TYPE — full table rewrite + exclusive lock
-- Widening customer_id from INTEGER to BIGINT for new UUID-based customer IDs
ALTER TABLE orders.cpt_order
    ALTER COLUMN customer_id TYPE BIGINT;

-- DBA_REVIEW #2: ALTER COLUMN TYPE — widening status_cd for new fulfillment statuses
ALTER TABLE orders.cpt_order
    ALTER COLUMN status_cd TYPE VARCHAR(100)
    USING status_cd::VARCHAR(100);

-- DBA_REVIEW #3: CREATE INDEX without IF NOT EXISTS
-- Missing idempotency guard — will fail on Flyway retry
CREATE INDEX idx_cpt_order_loyalty_tier ON orders.cpt_order(loyalty_tier_cd);

-- DBA_REVIEW #4: DROP COLUMN — destructive, removes data
-- Confirmed: old_promo_ref_cd removed from cart-service v5.1 but requires DBA sign-off
ALTER TABLE IF EXISTS orders.cpt_order DROP COLUMN IF EXISTS old_promo_ref_cd;

-- DBA_REVIEW #5: ALTER SEQUENCE — changes INCREMENT BY (real production revert pattern)
ALTER SEQUENCE orders.cpt_order_order_id_seq INCREMENT BY 10;

-- New loyalty tier lookup table — all guards and audit columns present (CLEAN)
CREATE TABLE IF NOT EXISTS orders.cpt_loyalty_tier (
    tier_cd         VARCHAR(20)   NOT NULL,
    tier_tx         VARCHAR(100)  NOT NULL,
    min_spend_amt   NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    discount_pct    NUMERIC(5,2)  NOT NULL DEFAULT 0.00,
    active_fl       CHAR(1)       NOT NULL DEFAULT 'Y',
    audt_cr_dt_tm   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id      VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id     VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER,
    CONSTRAINT pk_cpt_loyalty_tier PRIMARY KEY (tier_cd)
);

CREATE INDEX IF NOT EXISTS idx_cpt_loyalty_tier_spend ON orders.cpt_loyalty_tier(min_spend_amt);
