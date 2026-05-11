-- Add a new flag column and clean up legacy rows.
ALTER TABLE public.orders
    ADD COLUMN is_archived BOOLEAN DEFAULT FALSE;

DELETE FROM public.orders_audit;

UPDATE public.orders
    SET status = 'CLOSED';

