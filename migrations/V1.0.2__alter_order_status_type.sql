-- V1.0.2__alter_order_status_type.sql
-- Changes status_cd column type from VARCHAR(20) to VARCHAR(50)
-- to support longer status codes from the new fulfillment system

ALTER TABLE orders.cpt_order ALTER COLUMN status_cd TYPE VARCHAR(50);

-- Also adding an index on customer + status for reporting queries
CREATE INDEX idx_cpt_order_customer_status ON orders.cpt_order(customer_id, status_cd);

ALTER SEQUENCE orders.cpt_order_order_id_seq INCREMENT BY 5;
