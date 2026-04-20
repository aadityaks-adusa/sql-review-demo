-- Migration: add product variant table for online catalog

-- D9: CREATE TABLE without IF NOT EXISTS — Flyway retry fails
CREATE TABLE onlinecatalog.product_variant (
    variant_id       SERIAL          PRIMARY KEY,
    product_id       BIGINT          NOT NULL,
    variant_nm       VARCHAR(200)    NOT NULL,
    sku_cd           VARCHAR(100)    NOT NULL,
    price_amt        NUMERIC(12, 2),
    audt_cr_dt_tm    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id       VARCHAR(100)    NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm   TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id      VARCHAR(100)    NOT NULL DEFAULT CURRENT_USER
);

-- D10: CREATE INDEX without IF NOT EXISTS — Flyway retry fails
CREATE INDEX idx_product_variant_sku ON onlinecatalog.product_variant (sku_cd);
