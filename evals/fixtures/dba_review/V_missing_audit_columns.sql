-- EVAL FIXTURE: dba_review/missing_audit_columns.sql
-- File type: DDL_versioned (V*.sql)
-- Expected tier: DBA_REVIEW
-- Rule: CREATE TABLE missing audit columns

CREATE TABLE IF NOT EXISTS orders.cpt_notification (
    notification_id   BIGSERIAL    NOT NULL,
    order_id          BIGINT       NOT NULL,
    message_tx        VARCHAR(500) NOT NULL,
    sent_fl           CHAR(1)      NOT NULL DEFAULT 'N',
    CONSTRAINT pk_cpt_notification PRIMARY KEY (notification_id)
);
