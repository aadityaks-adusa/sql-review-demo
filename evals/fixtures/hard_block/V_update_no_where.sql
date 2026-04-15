-- EVAL FIXTURE: hard_block/update_no_where.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: HARD_BLOCK
-- Rule: UPDATE without WHERE clause

UPDATE orders.cpt_order SET status_cd = 'CANCELLED';
