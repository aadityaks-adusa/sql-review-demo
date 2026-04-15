-- R__fn_search_orders.sql
-- Repeatable migration — full-text search function for orders
-- Re-runs automatically whenever this file changes

CREATE OR REPLACE FUNCTION orders.fn_search_orders(
    p_customer_id BIGINT,
    p_search_term VARCHAR(500)
)
RETURNS TABLE (
    order_id       BIGINT,
    status_cd      VARCHAR(100),
    total_amt      NUMERIC(12,2),
    created_dt_tm  TIMESTAMP,
    relevance_score FLOAT
)
LANGUAGE plpgsql
STABLE
AS $function$
BEGIN
    -- Log search for personalization tracking
    INSERT INTO orders.cpt_order_search_history (customer_id, search_term_tx, result_count_nb)
    VALUES (p_customer_id, p_search_term, 0);

    -- Return matching orders sorted by relevance
    RETURN QUERY
    SELECT
        o.order_id,
        o.status_cd,
        COALESCE(SUM(i.line_total_amt), 0.00) AS total_amt,
        o.audt_cr_dt_tm                        AS created_dt_tm,
        -- Simple relevance: boost recent orders
        EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - o.audt_cr_dt_tm)) * -1 AS relevance_score
    FROM orders.cpt_order o
    LEFT JOIN orders.cpt_order_item i ON i.order_id = o.order_id
    WHERE o.customer_id = p_customer_id
      AND (p_search_term IS NULL OR o.notes_tx ILIKE '%' || p_search_term || '%')
    GROUP BY o.order_id, o.status_cd, o.audt_cr_dt_tm
    ORDER BY relevance_score DESC
    LIMIT 50;
END;
$function$;

COMMENT ON FUNCTION orders.fn_search_orders(BIGINT, VARCHAR)
    IS 'Full-text order search for customer self-service and CSR tools';

GRANT EXECUTE ON FUNCTION orders.fn_search_orders(BIGINT, VARCHAR) TO app_cart_role;
GRANT EXECUTE ON FUNCTION orders.fn_search_orders(BIGINT, VARCHAR) TO app_cart_admin;
