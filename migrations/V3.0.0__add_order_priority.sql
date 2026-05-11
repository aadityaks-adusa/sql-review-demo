-- Adds a nullable priority column for orders. Idempotent — safe for Flyway retries.
ALTER TABLE IF EXISTS public.orders
    ADD COLUMN IF NOT EXISTS priority SMALLINT;

COMMENT ON COLUMN public.orders.priority IS 'Optional order priority (1=low, 5=high)';
