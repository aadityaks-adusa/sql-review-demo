-- EVAL FIXTURE: hard_block/delete_no_where.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: HARD_BLOCK
-- Rule: DELETE FROM without WHERE clause

DELETE FROM orders.cpt_order;
DELETE FROM orders.cpt_order_item;
