-- EVAL FIXTURE: hard_block/add_column_no_guard.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: HARD_BLOCK
-- Rule: ADD COLUMN without IF NOT EXISTS

ALTER TABLE orders.cpt_order ADD COLUMN discount_pct NUMERIC(5,2);
ALTER TABLE orders.cpt_order_item ADD COLUMN promo_cd VARCHAR(20);
