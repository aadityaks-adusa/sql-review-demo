-- V2.0.0__order_fulfillment.sql
-- JIRA: OCDOMAIN-20100
-- Adds fulfillment tracking columns and a new warehouse_slot lookup table

-- ⚠️ DEMO: This file intentionally contains issues to demonstrate the AI review gate.

-- Hard block #1: ADD COLUMN without IF NOT EXISTS guard
-- AI will flag this: Flyway retry will crash with "column already exists"
ALTER TABLE orders.cpt_order ADD COLUMN fulfillment_type_cd VARCHAR(30);
ALTER TABLE orders.cpt_order ADD COLUMN warehouse_slot_id   BIGINT;
ALTER TABLE orders.cpt_order ADD COLUMN shipped_dt_tm       TIMESTAMP;

-- Hard block #2: UPDATE without WHERE — modifies every row in the table
UPDATE orders.cpt_order SET fulfillment_type_cd = 'STANDARD';

-- Hard block #3: CREATE TABLE without IF NOT EXISTS guard
CREATE TABLE orders.cpt_warehouse_slot (
    slot_id         BIGSERIAL    NOT NULL,
    warehouse_cd    VARCHAR(10)  NOT NULL,
    slot_cd         VARCHAR(20)  NOT NULL,
    capacity_nb     INTEGER      NOT NULL DEFAULT 100,
    active_fl       CHAR(1)      NOT NULL DEFAULT 'Y',
    CONSTRAINT pk_cpt_warehouse_slot PRIMARY KEY (slot_id)
);

-- (Also: missing all 4 audit columns on the new table — DBA_REVIEW will also fire)

-- Index — also missing IF NOT EXISTS
CREATE INDEX idx_cpt_order_fulfillment ON orders.cpt_order(fulfillment_type_cd);
