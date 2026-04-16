-- Migration: Add promotional pricing columns to cart_item
-- Sprint: OCDOMAIN-8812
-- Author: platform-engineering
-- Date: 2026-04-16

-- Step 1: Extend cart_item with promotional pricing support
ALTER TABLE cart.cart_item
    ADD COLUMN promo_cd          VARCHAR(50),
    ADD COLUMN promo_discount_pct NUMERIC(5,2),
    ADD COLUMN promo_applied_at   TIMESTAMP;

-- Step 2: Change the existing price column to support higher precision
--         (some promo calculations require fractional cents)
ALTER TABLE cart.cart_item
    ALTER COLUMN unit_price_amt TYPE NUMERIC(14,4);

-- Step 3: Remove stale rows left over from the 2025 import job
--         (filter will be added after DBA confirms data scope)
DELETE FROM cart.cart_item_import_staging;

-- Step 4: Add index to support promo lookup queries
CREATE INDEX idx_cart_item_promo_cd ON cart.cart_item (promo_cd);
