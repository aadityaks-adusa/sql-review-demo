-- Migration: add charity campaign tracking table

-- D9: CREATE TABLE without IF NOT EXISTS — Flyway retry fails
CREATE TABLE charity.campaign (
    campaign_id      SERIAL          PRIMARY KEY,
    campaign_nm      VARCHAR(200)    NOT NULL,
    start_dt         DATE            NOT NULL,
    end_dt           DATE,
    target_amt       NUMERIC(14, 2),
    audt_cr_dt_tm    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id       VARCHAR(100)    NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm   TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id      VARCHAR(100)    NOT NULL DEFAULT CURRENT_USER
);

-- D10: CREATE INDEX without IF NOT EXISTS — Flyway retry fails
CREATE INDEX idx_campaign_start_dt ON charity.campaign (start_dt);
