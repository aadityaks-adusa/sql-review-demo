-- Migration: add curbside pickup support to store locator

-- H1: ADD COLUMN without IF NOT EXISTS — Flyway retry crash risk
ALTER TABLE storelocator.store
    ADD COLUMN curbside_pickup_flg  BOOLEAN DEFAULT FALSE,
    ADD COLUMN curbside_hours_txt   VARCHAR(200);

-- D9: CREATE TABLE without IF NOT EXISTS — Flyway retry fails
CREATE TABLE storelocator.curbside_pickup_slot (
    slot_id          SERIAL          PRIMARY KEY,
    store_id         BIGINT          NOT NULL,
    slot_start_tm    TIME            NOT NULL,
    slot_end_tm      TIME            NOT NULL,
    audt_cr_dt_tm    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id       VARCHAR(100)    NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm   TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id      VARCHAR(100)    NOT NULL DEFAULT CURRENT_USER
);
