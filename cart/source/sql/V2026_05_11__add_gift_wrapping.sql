-- Migration: add gift wrapping feature to cart and update item status

-- H1: ADD COLUMN without IF NOT EXISTS — crash on Flyway retry (OCDOMAIN-15294)
ALTER TABLE cart.cart_item
    ADD COLUMN gift_wrap_flg     BOOLEAN DEFAULT FALSE,
    ADD COLUMN gift_message_txt  VARCHAR(500);

-- H4: UPDATE without WHERE — modifies every row in the table
UPDATE cart.cart_item
SET    item_status_cd = 'PENDING';

-- D8: RENAME COLUMN — breaking change; app must update atomically
ALTER TABLE cart.cart
    RENAME COLUMN customer_email TO customer_email_addr;
