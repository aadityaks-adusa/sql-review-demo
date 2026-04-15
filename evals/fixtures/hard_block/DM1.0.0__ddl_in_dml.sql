-- EVAL FIXTURE: hard_block/ddl_in_dml.sql
-- File type: DML (DM*.sql)
-- Expected tier: HARD_BLOCK
-- Rule: DDL inside a DML file

ALTER TABLE orders.cpt_order ADD COLUMN notes_tx VARCHAR(500);
INSERT INTO orders.cpt_order (order_id, status_cd) VALUES (999, 'NEW');
