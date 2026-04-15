-- V2.0.2__order_search_enhancements.sql
-- JIRA: OCDOMAIN-20130
-- Adds full-text search support for order notes + search history tracking

-- All guards present — this should be completely CLEAN

-- Add search-optimized columns (all nullable, ADD COLUMN IF NOT EXISTS)
ALTER TABLE IF EXISTS orders.cpt_order
    ADD COLUMN IF NOT EXISTS search_vector_tx   TEXT,
    ADD COLUMN IF NOT EXISTS last_searched_dt_tm TIMESTAMP;

-- Search history tracking table — all 4 audit columns, all guards
CREATE TABLE IF NOT EXISTS orders.cpt_order_search_history (
    search_id         BIGSERIAL     NOT NULL,
    customer_id       BIGINT        NOT NULL,
    search_term_tx    VARCHAR(500)  NOT NULL,
    result_count_nb   INTEGER       NOT NULL DEFAULT 0,
    search_dt_tm      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_dt_tm     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_cr_id        VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER,
    audt_upd_dt_tm    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audt_upd_id       VARCHAR(50)   NOT NULL DEFAULT CURRENT_USER,
    CONSTRAINT pk_cpt_order_search_history PRIMARY KEY (search_id)
);

COMMENT ON TABLE  orders.cpt_order_search_history                  IS 'Tracks customer order search history for personalization';
COMMENT ON COLUMN orders.cpt_order_search_history.search_term_tx   IS 'The search string entered by the customer';
COMMENT ON COLUMN orders.cpt_order_search_history.result_count_nb  IS 'Number of orders returned for this search';

-- All indexes with IF NOT EXISTS guards ✅
CREATE INDEX IF NOT EXISTS idx_cpt_order_search_customer  ON orders.cpt_order_search_history(customer_id);
CREATE INDEX IF NOT EXISTS idx_cpt_order_search_term      ON orders.cpt_order_search_history(search_term_tx);
CREATE INDEX IF NOT EXISTS idx_cpt_order_search_dt        ON orders.cpt_order_search_history(search_dt_tm DESC);
CREATE INDEX IF NOT EXISTS idx_cpt_order_search_vector    ON orders.cpt_order(search_vector_tx) WHERE search_vector_tx IS NOT NULL;

GRANT SELECT, INSERT, UPDATE ON orders.cpt_order_search_history TO app_cart_role;
GRANT SELECT, INSERT, UPDATE ON orders.cpt_order_search_history TO app_cart_admin;
