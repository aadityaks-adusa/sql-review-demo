-- Migration: add refund tracking columns to payments.payment_transaction

-- H1: ADD COLUMN without IF NOT EXISTS — crash on Flyway retry
ALTER TABLE payments.payment_transaction
    ADD COLUMN refund_amt        NUMERIC(12, 2),
    ADD COLUMN refund_reason_cd  VARCHAR(50);

-- D1: ALTER COLUMN TYPE — full row rewrite + exclusive table lock
ALTER TABLE payments.payment_transaction
    ALTER COLUMN transaction_amt TYPE NUMERIC(14, 2) USING transaction_amt::NUMERIC(14, 2);

-- H3: DELETE FROM without WHERE — wipes entire staging table
DELETE FROM payments.payment_transaction_import;
