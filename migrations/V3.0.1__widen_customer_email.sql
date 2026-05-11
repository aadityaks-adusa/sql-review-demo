-- Widen email column to accommodate longer addresses (RFC 5321 max = 320 chars).
ALTER TABLE public.customers
    ALTER COLUMN email TYPE VARCHAR(320);
