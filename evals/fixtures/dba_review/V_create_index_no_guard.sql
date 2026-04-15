-- EVAL FIXTURE: dba_review/create_index_no_guard.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: DBA_REVIEW
-- Rule: CREATE INDEX without IF NOT EXISTS

CREATE INDEX idx_cpt_order_status ON orders.cpt_order(status_cd);
CREATE INDEX idx_cpt_order_customer ON orders.cpt_order(customer_id);
