-- EVAL FIXTURE: clean/repeatable_function_with_truncate.sql
-- File type: DDL_repeatable (R__*.sql)
-- Expected tier: CLEAN
-- TRUNCATE inside a function body is legitimate ETL — must NOT be flagged

CREATE OR REPLACE FUNCTION orders.fn_refresh_order_summary()
RETURNS VOID
LANGUAGE plpgsql
AS $function$
BEGIN
    -- Legitimate ETL: truncate the summary staging table before refresh
    TRUNCATE TABLE orders.cpt_order_summary_stg;

    INSERT INTO orders.cpt_order_summary_stg (order_id, total_amt)
    SELECT order_id, SUM(line_total_amt)
    FROM   orders.cpt_order_item
    GROUP BY order_id;

    -- Also legitimate: DELETE inside function body
    DELETE FROM orders.cpt_order_summary WHERE status_cd = 'EXPIRED';
END;
$function$;
