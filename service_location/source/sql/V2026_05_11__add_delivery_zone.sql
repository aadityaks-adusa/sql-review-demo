-- Migration: add delivery zone tracking to service location

-- H1: ADD COLUMN without IF NOT EXISTS — Flyway retry crash risk
ALTER TABLE service_location.service_address
    ADD COLUMN delivery_zone_cd  VARCHAR(20),
    ADD COLUMN delivery_eta_min  INTEGER;

-- D1: ALTER COLUMN TYPE — full row rewrite + exclusive lock
ALTER TABLE service_location.service_address
    ALTER COLUMN postal_cd TYPE VARCHAR(20) USING postal_cd::VARCHAR(20);

-- H3: DELETE without WHERE — wipes the entire staging table
DELETE FROM service_location.service_address_staging;
