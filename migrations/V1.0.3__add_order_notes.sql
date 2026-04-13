-- V1.0.3__add_order_notes.sql
-- Adds optional free-text notes column to cpt_order
-- and a lookup table for order cancellation reasons
--
-- All idempotency guards present, audit columns included

-- Add nullable notes column — safe: no NOT NULL, no DEFAULT needed
ALTER TABLE IF EXISTS orders.cpt_order
    ADD COLUMN IF NOT EXISTS notes_tx VARCHAR(500);

-- New lookup table for cancellation reasons
CREATE TABLE IF NOT EXISTS orders.cpt_cancel_reason (
    cancel_reason_cd  VARCHAR(20)   NOT NULL,
    cancel_reason_tx  VARCHAR(200)  NOT NULL,
    active_fl         CHAR(1)       NOT NULL DEFAULT 'Y',
    audt_cr_dt_tm     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id        VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id       VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER,
    CONSTRAINT pk_cpt_cancel_reason PRIMARY KEY (cancel_reason_cd)
);

-- Seed initial cancellation reasons
INSERT INTO orders.cpt_cancel_reason (cancel_reason_cd, cancel_reason_tx) VALUES
    ('CUST_REQ',  'Customer requested cancellation'),
    ('OUT_STOCK', 'Item out of stock'),
    ('FRAUD',     'Suspected fraudulent order'),
    ('DUPLICATE', 'Duplicate order detected')
ON CONFLICT (cancel_reason_cd) DO NOTHING;

-- Index with IF NOT EXISTS guard (Flyway-safe)
CREATE INDEX IF NOT EXISTS idx_cpt_order_notes ON orders.cpt_order(notes_tx)
    WHERE notes_tx IS NOT NULL;

COMMENT ON COLUMN orders.cpt_order.notes_tx          IS 'Optional free-text order notes from customer or CSR';
COMMENT ON TABLE  orders.cpt_cancel_reason            IS 'Lookup table for valid order cancellation reason codes';
