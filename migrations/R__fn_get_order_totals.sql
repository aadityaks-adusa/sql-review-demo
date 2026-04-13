-- R__fn_get_order_totals.sql
-- Repeatable migration — recalculates and returns order financial totals
-- Re-runs automatically whenever this file changes

CREATE OR REPLACE FUNCTION promotions.fn_get_order_totals(
    p_order_id BIGINT
)
RETURNS TABLE (
    order_id          BIGINT,
    subtotal_amt      NUMERIC(12,2),
    discount_amt      NUMERIC(12,2),
    tax_amt           NUMERIC(12,2),
    total_amt         NUMERIC(12,2),
    promotion_cd      VARCHAR(50),
    voucher_cd        VARCHAR(36)
)
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
    v_subtotal    NUMERIC(12,2) := 0;
    v_discount    NUMERIC(12,2) := 0;
    v_tax_rate    NUMERIC(5,4)  := 0.08;
BEGIN
    -- Aggregate line items to get subtotal
    SELECT COALESCE(SUM(line_total_amt), 0)
    INTO   v_subtotal
    FROM   orders.cpt_order_item
    WHERE  order_id = p_order_id;

    -- Pull applied discount from order header
    SELECT COALESCE(o.discount_amt, 0)
    INTO   v_discount
    FROM   orders.cpt_order o
    WHERE  o.order_id = p_order_id;

    RETURN QUERY
    SELECT
        o.order_id,
        v_subtotal                                              AS subtotal_amt,
        v_discount                                             AS discount_amt,
        ROUND((v_subtotal - v_discount) * v_tax_rate, 2)       AS tax_amt,
        ROUND((v_subtotal - v_discount) * (1 + v_tax_rate), 2) AS total_amt,
        p.promotion_cd,
        o.voucher_cd
    FROM orders.cpt_order o
    LEFT JOIN promotions.cpt_promotion p
           ON p.promotion_id = o.applied_promotion_id
    WHERE o.order_id = p_order_id;

END;
$function$;

COMMENT ON FUNCTION promotions.fn_get_order_totals(BIGINT)
    IS 'Returns full financial breakdown for an order including promotion and tax';

GRANT EXECUTE ON FUNCTION promotions.fn_get_order_totals(BIGINT) TO app_cart_role;
GRANT EXECUTE ON FUNCTION promotions.fn_get_order_totals(BIGINT) TO app_cart_admin;
