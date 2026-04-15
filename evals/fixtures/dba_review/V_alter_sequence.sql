-- EVAL FIXTURE: dba_review/alter_sequence.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: DBA_REVIEW
-- Rule: ALTER SEQUENCE with non-OWNED BY change

ALTER SEQUENCE orders.cpt_order_order_id_seq INCREMENT BY 5;
ALTER SEQUENCE orders.cpt_order_order_id_seq RESTART WITH 1000;
