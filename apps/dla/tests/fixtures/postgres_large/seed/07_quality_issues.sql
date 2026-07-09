-- File 07: deliberately seeded data-quality issues (6 tables, analytics schema).
-- Expected readiness detections:
--   Q1. empty_table       analytics.quality_empty_orders (zero rows)     -> Critical
--   Q2. all_null_column   analytics.quality_users.middle_name            -> Critical
--   Q3. constant_column   analytics.quality_users.country_code ('IN')    -> Info
--   Q4. high_null_rate    analytics.quality_users.referral_code (~70%)   -> Warning
--   Q5. broken_fk (inferred)  analytics.quality_invoices.dim_customer_id has
--       orphans vs sales.dim_customers.id (name matches "dim_customer_id")
--   Q6. broken_fk (DECLARED, NOT VALID)  analytics.quality_orders_notvalid.customer_ref
--       -> sales.dim_customers(id) added NOT VALID after orphan rows were inserted,
--       so a *declared* FK carries orphan values.
--   Q7. NOT expected to be caught (known gaps, for the report):
--       - analytics.quality_status_mix.status mixes 'active'/'Active'/'ACTIVE'
--         (case-inconsistent categorical) — no such check exists in M2.
--       - type_mismatch is documented as planned/deferred.
--   Q8. constant + all-null combo: analytics.quality_sensor_dump.firmware ('1.0.0'
--       constant) and calibration_note (all NULL).

SET client_min_messages = WARNING;
SET search_path = analytics;

CREATE TABLE quality_empty_orders (
    id           SERIAL PRIMARY KEY,
    placed_at    TIMESTAMPTZ NOT NULL,
    customer_id  INTEGER NOT NULL,
    status       VARCHAR(24)
);

CREATE TABLE quality_users (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(255) NOT NULL,
    middle_name   VARCHAR(80),      -- always NULL (Q2)
    country_code  CHAR(2) NOT NULL, -- always 'IN' (Q3)
    referral_code VARCHAR(40)       -- ~70% NULL (Q4)
);

INSERT INTO quality_users (email, middle_name, country_code, referral_code)
SELECT 'qu' || i || '@example.com', NULL, 'IN',
       CASE WHEN i % 10 < 3 THEN 'REF-' || i END
FROM generate_series(1, 200) i;

-- Q5: inferred relationship with orphans. "dim_customer_id" name-matches
-- sales.dim_customers (single-col PK), but 40 of 200 values do not exist there.
CREATE TABLE quality_invoices (
    id               SERIAL PRIMARY KEY,
    dim_customer_id  INTEGER NOT NULL,
    amount           NUMERIC(10,2) NOT NULL,
    issued_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO quality_invoices (dim_customer_id, amount)
SELECT CASE WHEN i % 5 = 0 THEN 90000 + i ELSE 1 + (i % 400) END,
       round((10 + i)::numeric, 2)
FROM generate_series(1, 200) i;

-- Q6: DECLARED broken FK via NOT VALID (constraint exists; orphans persist).
CREATE TABLE quality_orders_notvalid (
    id            SERIAL PRIMARY KEY,
    customer_ref  INTEGER NOT NULL,
    total         NUMERIC(12,2)
);

INSERT INTO quality_orders_notvalid (customer_ref, total)
SELECT CASE WHEN i % 4 = 0 THEN 77000 + i ELSE 1 + (i % 400) END,
       round((20 + i)::numeric, 2)
FROM generate_series(1, 100) i;

ALTER TABLE quality_orders_notvalid
    ADD CONSTRAINT fk_qonv_customer FOREIGN KEY (customer_ref)
    REFERENCES sales.dim_customers(id) NOT VALID;

-- Q7: mixed-case categorical (known detection gap — expect NO readiness issue)
CREATE TABLE quality_status_mix (
    id      SERIAL PRIMARY KEY,
    label   VARCHAR(80) NOT NULL,
    status  VARCHAR(24) NOT NULL
);

INSERT INTO quality_status_mix (label, status)
SELECT 'row ' || i, (ARRAY['active', 'Active', 'ACTIVE', 'inactive'])[1 + i % 4]
FROM generate_series(1, 120) i;

-- Q8: constant + all-null combo on one table
CREATE TABLE quality_sensor_dump (
    id               SERIAL PRIMARY KEY,
    reading          NUMERIC(12,4) NOT NULL,
    firmware         VARCHAR(16) NOT NULL,   -- constant '1.0.0'
    calibration_note TEXT                    -- all NULL
);

INSERT INTO quality_sensor_dump (reading, firmware, calibration_note)
SELECT round((random() * 100)::numeric, 4), '1.0.0', NULL
FROM generate_series(1, 150) i;
