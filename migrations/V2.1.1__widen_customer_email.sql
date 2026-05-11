-- Widen email column to accommodate longer addresses.
ALTER TABLE public.customers
    ALTER COLUMN email TYPE VARCHAR(320);

