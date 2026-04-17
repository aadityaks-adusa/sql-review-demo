-- Migration: add payment_method_token column to payments table
-- All idempotency guards in place, audit columns present.

ALTER TABLE IF EXISTS payments.payment_method
    ADD COLUMN IF NOT EXISTS token_hash VARCHAR(512),
    ADD COLUMN IF NOT EXISTS token_last_four CHAR(4);

CREATE TABLE IF NOT EXISTS payments.payment_token_audit (
    audit_id        BIGSERIAL       PRIMARY KEY,
    payment_id      BIGINT          NOT NULL,
    action_cd       VARCHAR(20)     NOT NULL,
    audt_cr_dt_tm   TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id      VARCHAR(100)    NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm  TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id     VARCHAR(100)    NOT NULL DEFAULT CURRENT_USER
);

CREATE INDEX IF NOT EXISTS idx_payment_token_audit_payment_id
    ON payments.payment_token_audit (payment_id);
