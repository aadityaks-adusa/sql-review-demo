-- V1.0.0__create_orders_schema.sql
-- Initial schema: orders and order_items tables
-- Clean migration — all idempotency guards present, audit columns included

CREATE TABLE IF NOT EXISTS orders.cpt_order (
    order_id          BIGSERIAL PRIMARY KEY,
    customer_id       BIGINT        NOT NULL,
    store_cd          VARCHAR(10)   NOT NULL,
    status_cd         VARCHAR(20)   NOT NULL DEFAULT 'PENDING',
    total_amt         NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    audt_cr_dt_tm     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id        VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id       VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER
);

CREATE TABLE IF NOT EXISTS orders.cpt_order_item (
    order_item_id     BIGSERIAL PRIMARY KEY,
    order_id          BIGINT        NOT NULL REFERENCES orders.cpt_order(order_id),
    product_id        BIGINT        NOT NULL,
    quantity          INTEGER       NOT NULL DEFAULT 1,
    unit_price        NUMERIC(10,2) NOT NULL,
    audt_cr_dt_tm     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id        VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id       VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER
);

-- Indexes with IF NOT EXISTS guards (Flyway-safe)
CREATE INDEX IF NOT EXISTS idx_cpt_order_customer_id ON orders.cpt_order(customer_id);
CREATE INDEX IF NOT EXISTS idx_cpt_order_status_cd   ON orders.cpt_order(status_cd);
CREATE INDEX IF NOT EXISTS idx_cpt_order_item_order  ON orders.cpt_order_item(order_id);

COMMENT ON TABLE orders.cpt_order      IS 'Core order header table';
COMMENT ON TABLE orders.cpt_order_item IS 'Individual line items per order';
