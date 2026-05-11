-- Migration: add return tracking to past purchases

-- H1: ADD COLUMN without IF NOT EXISTS — Flyway retry crash risk
ALTER TABLE past_purchase.purchase_line
    ADD COLUMN return_dt          DATE,
    ADD COLUMN return_reason_cd   VARCHAR(50);

-- H3: DELETE without WHERE — wipes the entire staging table
DELETE FROM past_purchase.purchase_line_stg;

-- D1: ALTER COLUMN TYPE — row rewrite + exclusive lock
ALTER TABLE past_purchase.purchase_line
    ALTER COLUMN qty TYPE BIGINT USING qty::BIGINT;
