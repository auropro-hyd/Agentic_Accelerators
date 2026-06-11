-- M2 readiness fixture overlay. Layered on top of 01_clean.sql:
--   * adds tables that exhibit specific quality issues, so the readiness
--     report has known-good inputs to detect.
--   * does NOT modify the clean retail tables, so M1 demos still work.
--
-- Seeded issues (with expected detection):
--   E1. empty_table:        public.quality_empty_orders (zero rows)
--   E2. all_null_column:    public.quality_users.middle_name (every row NULL)
--   E3. constant_column:    public.quality_users.country_code (every row 'IN')
--   E4. high_null_rate:     public.quality_users.referral_code (~70% NULL)
--   E5. broken_fk:          public.quality_invoices.customer_id has values that
--                           do not exist in public.customers (orphan keys);
--                           there's no declared FK, so this becomes an
--                           inferred-relationship-with-orphans issue.
--   E6. unprofiled:         (deferred — exercised by simulating a permission
--                           error in tests via a connection mock, not in SQL)

CREATE TABLE quality_empty_orders (
    id           SERIAL PRIMARY KEY,
    placed_at    TIMESTAMPTZ NOT NULL,
    customer_id  INTEGER NOT NULL
);

CREATE TABLE quality_users (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(255) NOT NULL,
    middle_name   VARCHAR(80),     -- always NULL in this seed (E2)
    country_code  CHAR(2) NOT NULL, -- always 'IN' (E3 — constant column)
    referral_code VARCHAR(40)       -- ~70% NULL (E4 — high null rate)
);

INSERT INTO quality_users (email, middle_name, country_code, referral_code) VALUES
    ('u01@example.com', NULL, 'IN', 'PROMO-1'),
    ('u02@example.com', NULL, 'IN', NULL),
    ('u03@example.com', NULL, 'IN', NULL),
    ('u04@example.com', NULL, 'IN', NULL),
    ('u05@example.com', NULL, 'IN', NULL),
    ('u06@example.com', NULL, 'IN', NULL),
    ('u07@example.com', NULL, 'IN', NULL),
    ('u08@example.com', NULL, 'IN', 'PROMO-2'),
    ('u09@example.com', NULL, 'IN', 'PROMO-3'),
    ('u10@example.com', NULL, 'IN', NULL);

-- E5: invoices "belong to" customers but the FK isn't declared, and some
-- customer_id values do not exist in public.customers. Readiness flags this
-- as broken_fk (critical).
CREATE TABLE quality_invoices (
    id            SERIAL PRIMARY KEY,
    customer_id   INTEGER NOT NULL,        -- references public.customers(id) — INFERRED, not declared
    amount        NUMERIC(10, 2) NOT NULL,
    issued_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO quality_invoices (customer_id, amount) VALUES
    (1,     19.99),   -- exists in customers
    (2,     49.50),   -- exists
    (999,   12.00),   -- ORPHAN
    (1000,  35.00),   -- ORPHAN
    (3,     89.00);   -- exists
