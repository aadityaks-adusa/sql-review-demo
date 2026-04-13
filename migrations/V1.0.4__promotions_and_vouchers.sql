-- V1.0.4__promotions.sql
-- Promotions & vouchers schema — initial creation
-- Author: platform-eng | JIRA: OCDOMAIN-19842

-- ---------------------------------------------------------------------------
-- Schema setup
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS promotions;

GRANT USAGE  ON SCHEMA promotions TO app_cart_role;
GRANT CREATE ON SCHEMA promotions TO app_cart_admin;

-- ---------------------------------------------------------------------------
-- Legacy cleanup — remove deprecated column no longer used by any app
-- (confirmed removed from cart-service v4.2 and cartorders-service v3.1)
-- ---------------------------------------------------------------------------
ALTER TABLE IF EXISTS orders.cpt_order DROP COLUMN IF EXISTS legacy_ref_cd;

-- ---------------------------------------------------------------------------
-- Widen experiment_variant_cd accepted values (new A/B test system)
-- OCDOMAIN-19801: experiment codes are now UUIDs (36 chars), was VARCHAR(20)
-- ---------------------------------------------------------------------------
ALTER TABLE IF EXISTS orders.cpt_order
    ALTER COLUMN status_cd TYPE VARCHAR(100)
    USING status_cd::VARCHAR(100);

-- ---------------------------------------------------------------------------
-- UUID extension — required for voucher code generation
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------------
-- promotions.cpt_promotion
-- Core promotion definition table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS promotions.cpt_promotion (
    promotion_id        BIGSERIAL                   NOT NULL,
    promotion_cd        VARCHAR(50)                 NOT NULL,
    promotion_tx        VARCHAR(200)                NOT NULL,
    promotion_type_cd   VARCHAR(30)                 NOT NULL,   -- PERCENT_OFF | FIXED_AMT | BOGO | FREE_SHIP
    discount_pct        NUMERIC(5, 2),                          -- used when type = PERCENT_OFF
    discount_amt        NUMERIC(12, 2),                         -- used when type = FIXED_AMT
    min_order_amt       NUMERIC(12, 2)              NOT NULL DEFAULT 0.00,
    max_uses_nb         INTEGER,                                -- NULL = unlimited
    uses_per_customer_nb INTEGER                   NOT NULL DEFAULT 1,
    start_dt            DATE                        NOT NULL,
    end_dt              DATE,
    stackable_fl        CHAR(1)                     NOT NULL DEFAULT 'N',
    active_fl           CHAR(1)                     NOT NULL DEFAULT 'Y',
    audt_cr_dt_tm       TIMESTAMP                   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id          VARCHAR(50)                 NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm      TIMESTAMP                   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id         VARCHAR(50)                 NOT NULL DEFAULT CURRENT_USER,
    CONSTRAINT pk_cpt_promotion          PRIMARY KEY (promotion_id),
    CONSTRAINT uq_cpt_promotion_cd       UNIQUE      (promotion_cd),
    CONSTRAINT ck_cpt_promotion_type     CHECK       (promotion_type_cd IN ('PERCENT_OFF','FIXED_AMT','BOGO','FREE_SHIP')),
    CONSTRAINT ck_cpt_promotion_dates    CHECK       (end_dt IS NULL OR end_dt >= start_dt),
    CONSTRAINT ck_cpt_promotion_active   CHECK       (active_fl IN ('Y','N')),
    CONSTRAINT ck_cpt_promotion_stack    CHECK       (stackable_fl IN ('Y','N'))
);

COMMENT ON TABLE  promotions.cpt_promotion                IS 'Core promotion / campaign definition';
COMMENT ON COLUMN promotions.cpt_promotion.promotion_type_cd IS 'PERCENT_OFF | FIXED_AMT | BOGO | FREE_SHIP';
COMMENT ON COLUMN promotions.cpt_promotion.stackable_fl       IS 'Y = can combine with other promotions';

CREATE INDEX IF NOT EXISTS idx_cpt_promotion_cd       ON promotions.cpt_promotion(promotion_cd);
CREATE INDEX IF NOT EXISTS idx_cpt_promotion_dates    ON promotions.cpt_promotion(start_dt, end_dt) WHERE active_fl = 'Y';
CREATE INDEX IF NOT EXISTS idx_cpt_promotion_type     ON promotions.cpt_promotion(promotion_type_cd, active_fl);

-- ---------------------------------------------------------------------------
-- promotions.cpt_voucher
-- Individual single-use voucher codes tied to a promotion
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS promotions.cpt_voucher (
    voucher_id          BIGSERIAL                   NOT NULL,
    voucher_cd          VARCHAR(36)                 NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    promotion_id        BIGINT                      NOT NULL,
    customer_id         BIGINT,                                 -- NULL = any customer can redeem
    redeemed_fl         CHAR(1)                     NOT NULL DEFAULT 'N',
    redeemed_dt_tm      TIMESTAMP,
    redeemed_order_id   BIGINT,
    expires_dt          DATE,
    audt_cr_dt_tm       TIMESTAMP                   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id          VARCHAR(50)                 NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm      TIMESTAMP                   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id         VARCHAR(50)                 NOT NULL DEFAULT CURRENT_USER,
    CONSTRAINT pk_cpt_voucher            PRIMARY KEY (voucher_id),
    CONSTRAINT uq_cpt_voucher_cd         UNIQUE      (voucher_cd),
    CONSTRAINT fk_cpt_voucher_promotion  FOREIGN KEY (promotion_id) REFERENCES promotions.cpt_promotion(promotion_id),
    CONSTRAINT ck_cpt_voucher_redeemed   CHECK       (redeemed_fl IN ('Y','N'))
);

COMMENT ON TABLE  promotions.cpt_voucher              IS 'Single-use voucher codes generated for a promotion';
COMMENT ON COLUMN promotions.cpt_voucher.voucher_cd   IS 'UUID-based unique voucher code — generated via gen_random_uuid()';
COMMENT ON COLUMN promotions.cpt_voucher.customer_id  IS 'NULL = open voucher; set = restricted to one customer';

CREATE INDEX IF NOT EXISTS idx_cpt_voucher_promotion  ON promotions.cpt_voucher(promotion_id);
CREATE INDEX IF NOT EXISTS idx_cpt_voucher_customer   ON promotions.cpt_voucher(customer_id) WHERE customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cpt_voucher_cd         ON promotions.cpt_voucher(voucher_cd);
CREATE INDEX IF NOT EXISTS idx_cpt_voucher_unredeemed ON promotions.cpt_voucher(expires_dt) WHERE redeemed_fl = 'N';

-- ---------------------------------------------------------------------------
-- promotions.cpt_promotion_rule
-- Eligibility rules attached to a promotion (product, category, brand)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS promotions.cpt_promotion_rule (
    rule_id             BIGSERIAL                   NOT NULL,
    promotion_id        BIGINT                      NOT NULL,
    rule_type_cd        VARCHAR(30)                 NOT NULL,   -- PRODUCT | CATEGORY | BRAND | MIN_QTY
    rule_value_tx       VARCHAR(200)                NOT NULL,
    operator_cd         VARCHAR(10)                 NOT NULL DEFAULT 'INCLUDE',  -- INCLUDE | EXCLUDE
    audt_cr_dt_tm       TIMESTAMP                   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id          VARCHAR(50)                 NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm      TIMESTAMP                   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id         VARCHAR(50)                 NOT NULL DEFAULT CURRENT_USER,
    CONSTRAINT pk_cpt_promotion_rule     PRIMARY KEY (rule_id),
    CONSTRAINT fk_cpt_promotion_rule_promo FOREIGN KEY (promotion_id) REFERENCES promotions.cpt_promotion(promotion_id),
    CONSTRAINT ck_cpt_promotion_rule_type CHECK (rule_type_cd IN ('PRODUCT','CATEGORY','BRAND','MIN_QTY')),
    CONSTRAINT ck_cpt_promotion_rule_op   CHECK (operator_cd IN ('INCLUDE','EXCLUDE'))
);

COMMENT ON TABLE promotions.cpt_promotion_rule IS 'Eligibility rules for a promotion (which products/categories apply)';

CREATE INDEX IF NOT EXISTS idx_cpt_promotion_rule_promo ON promotions.cpt_promotion_rule(promotion_id);

-- ---------------------------------------------------------------------------
-- Bridge: link applied promotions to orders
-- ---------------------------------------------------------------------------
ALTER TABLE IF EXISTS orders.cpt_order
    ADD COLUMN IF NOT EXISTS applied_promotion_id BIGINT,
    ADD COLUMN IF NOT EXISTS discount_amt         NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS voucher_cd           VARCHAR(36);

CREATE INDEX IF NOT EXISTS idx_cpt_order_promotion ON orders.cpt_order(applied_promotion_id) WHERE applied_promotion_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE ON promotions.cpt_promotion      TO app_cart_role;
GRANT SELECT, INSERT, UPDATE ON promotions.cpt_voucher         TO app_cart_role;
GRANT SELECT                 ON promotions.cpt_promotion_rule  TO app_cart_role;
GRANT SELECT, INSERT, UPDATE ON promotions.cpt_promotion       TO app_cart_admin;
GRANT SELECT, INSERT, UPDATE ON promotions.cpt_voucher         TO app_cart_admin;
GRANT SELECT, INSERT, UPDATE ON promotions.cpt_promotion_rule  TO app_cart_admin;
