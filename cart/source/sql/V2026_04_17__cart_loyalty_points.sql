-- Migration: add loyalty_points column to cart_item + purge staging
-- ⚠️  This file is intentionally seeded with HARD_BLOCK issues.

-- H1: ADD COLUMN without IF NOT EXISTS — Flyway retry crash (OCDOMAIN-15294)
ALTER TABLE cart.cart_item
    ADD COLUMN loyalty_points_earned INTEGER DEFAULT 0;

-- H3: DELETE FROM without WHERE — full-table wipe
DELETE FROM cart.cart_import_staging;
