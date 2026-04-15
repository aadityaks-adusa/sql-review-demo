-- EVAL FIXTURE: clean/guarded_migration.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: CLEAN
-- All idempotency guards present, audit columns included, no destructive ops

ALTER TABLE IF EXISTS orders.cpt_order
    ADD COLUMN IF NOT EXISTS notes_tx      VARCHAR(500),
    ADD COLUMN IF NOT EXISTS loyalty_tier  VARCHAR(20);

CREATE TABLE IF NOT EXISTS orders.cpt_notification (
    notification_id   BIGSERIAL    NOT NULL,
    order_id          BIGINT       NOT NULL,
    message_tx        VARCHAR(500) NOT NULL,
    sent_fl           CHAR(1)      NOT NULL DEFAULT 'N',
    audt_cr_dt_tm     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id        VARCHAR(50)  NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id       VARCHAR(50)  NOT NULL DEFAULT CURRENT_USER,
    CONSTRAINT pk_cpt_notification PRIMARY KEY (notification_id)
);

CREATE INDEX IF NOT EXISTS idx_cpt_notification_order ON orders.cpt_notification(order_id);
CREATE INDEX IF NOT EXISTS idx_cpt_order_loyalty ON orders.cpt_order(loyalty_tier) WHERE loyalty_tier IS NOT NULL;
