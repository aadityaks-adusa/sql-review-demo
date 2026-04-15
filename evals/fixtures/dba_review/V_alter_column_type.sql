-- EVAL FIXTURE: dba_review/alter_column_type.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: DBA_REVIEW (not HARD_BLOCK)
-- Rule: ALTER COLUMN TYPE without USING clause

ALTER TABLE orders.cpt_order ALTER COLUMN customer_id TYPE BIGINT;
ALTER TABLE orders.cpt_order ALTER COLUMN status_cd TYPE VARCHAR(100);
