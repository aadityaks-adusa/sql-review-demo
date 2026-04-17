-- Migration: add promo columns + clean up staging rows
-- ⚠️  This file is intentionally seeded with review issues for the demo.

-- H1: ADD COLUMN without IF NOT EXISTS (severity = HIGH, HARD_BLOCK)
ALTER TABLE cart.cart_item
    ADD COLUMN promo_cd             VARCHAR(50),
    ADD COLUMN promo_discount_pct   NUMERIC(5, 2);

-- D1: ALTER COLUMN TYPE — row-rewrite + exclusive lock (severity = MEDIUM, DBA_REVIEW)
ALTER TABLE cart.cart_item
    ALTER COLUMN item_qty TYPE BIGINT USING item_qty::BIGINT;

-- H3: DELETE without WHERE — full table wipe (severity = CRITICAL, HARD_BLOCK)
DELETE FROM cart.cart_import_staging;

-- D10: CREATE INDEX without IF NOT EXISTS (severity = LOW, DBA_REVIEW)
CREATE INDEX idx_cart_item_promo ON cart.cart_item (promo_cd);
