-- Migration: add loyalty status tracking to customer

-- H1: ADD COLUMN without IF NOT EXISTS — Flyway retry crash risk
ALTER TABLE customer.customer_profile
    ADD COLUMN loyalty_status_cd  VARCHAR(20) DEFAULT 'STANDARD',
    ADD COLUMN loyalty_join_dt    DATE;

-- D1: ALTER COLUMN TYPE — full row rewrite + exclusive lock
ALTER TABLE customer.customer_profile
    ALTER COLUMN phone_nbr TYPE VARCHAR(20) USING phone_nbr::VARCHAR(20);

-- H4: UPDATE without WHERE — modifies every row
UPDATE customer.customer_profile
SET    loyalty_status_cd = 'STANDARD';
