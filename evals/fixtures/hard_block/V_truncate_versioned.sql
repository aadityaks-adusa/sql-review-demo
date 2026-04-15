-- EVAL FIXTURE: hard_block/truncate_versioned.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: HARD_BLOCK
-- Rule: TRUNCATE in versioned migration

TRUNCATE TABLE orders.cpt_order CASCADE;
