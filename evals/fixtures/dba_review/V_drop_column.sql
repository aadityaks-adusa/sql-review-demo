-- EVAL FIXTURE: dba_review/drop_column.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: DBA_REVIEW
-- Rule: DROP COLUMN (destructive)

ALTER TABLE orders.cpt_order DROP COLUMN IF EXISTS legacy_ref_cd;
ALTER TABLE orders.cpt_order_item DROP COLUMN IF EXISTS old_price_amt;
