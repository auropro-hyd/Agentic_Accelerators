-- File 04: staging schema — the NO-FK zone (16 tables).
-- Simulates a cloud-warehouse dump: primary keys survive, foreign keys do not.
-- Zero declared FK constraints in this schema. Join paths must be INFERRED.
--
-- Inference ground truth (given the engine matches "<table>_id" /
-- "<table-minus-trailing-s>_id" against another table's single-column PK):
--   * stg_orders.stg_customer_id      -> stg_customers.id   name+type+overlap => Strong
--   * stg_order_items.stg_order_id    -> stg_orders.id      name+type+overlap => Strong
--   * stg_order_items.stg_product_id  -> stg_products.id    name+type+overlap => Strong
--   * stg_products.stg_category_id    -> stg_categories.id  name+type+overlap => Strong
--   * stg_payments.stg_invoice_id     -> stg_invoices.id    name+type+overlap => Strong
--   * stg_inventory.stg_product_id / stg_store_id           => Strong (table has no PK itself)
--   * stg_web_events.stg_customer_id  -> stg_customers.id   => Strong
--   * stg_shipments.stg_order_id (VARCHAR) -> stg_orders.id  name only (type mismatch) => Weak
--   * stg_returns.stg_order_id values are ORPHANS (900000+)  name+type, no overlap
--       -> inferred rel exists AND readiness should flag broken_fk on it
--   * stg_invoices.customer_id: realistic warehouse naming that does NOT match the
--       "stg_customers" pattern -> expected inference MISS (documents the engine's
--       naming-convention limitation)
--   * stg_web_events.store_id / stg_returns.store_id: matches the DISTRACTOR table
--       analytics.stores (not sales.dim_stores) -> deliberate false-positive bait

SET client_min_messages = WARNING;
SET search_path = staging;

CREATE TABLE stg_customers (
    id           INTEGER PRIMARY KEY,
    name         VARCHAR(160),
    email        VARCHAR(255),
    status       VARCHAR(24),
    created_at   TIMESTAMPTZ
);

CREATE TABLE stg_categories (
    id    INTEGER PRIMARY KEY,
    name  VARCHAR(80)
);

CREATE TABLE stg_products (
    id               INTEGER PRIMARY KEY,
    name             VARCHAR(160),
    stg_category_id  INTEGER,
    price            NUMERIC(10,2),
    status           VARCHAR(24)
);

CREATE TABLE stg_orders (
    id               INTEGER PRIMARY KEY,
    stg_customer_id  INTEGER,
    status           VARCHAR(24),
    order_total      NUMERIC(12,2),
    created_at       TIMESTAMPTZ
);

CREATE TABLE stg_order_items (
    id              INTEGER PRIMARY KEY,
    stg_order_id    INTEGER,
    stg_product_id  INTEGER,
    quantity        INTEGER,
    unit_price      NUMERIC(10,2)
);

CREATE TABLE stg_stores (
    id    INTEGER PRIMARY KEY,
    name  VARCHAR(120),
    city  VARCHAR(80)
);

CREATE TABLE stg_invoices (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER,            -- realistic naming; will NOT match stg_customers
    amount       NUMERIC(12,2),
    status       VARCHAR(24),
    issued_on    DATE
);

CREATE TABLE stg_payments (
    id              INTEGER PRIMARY KEY,
    stg_invoice_id  INTEGER,
    amount          NUMERIC(12,2),
    paid_on         DATE
);

CREATE TABLE stg_shipments (
    id            INTEGER PRIMARY KEY,
    stg_order_id  VARCHAR(24),       -- TYPE MISMATCH with stg_orders.id (INTEGER)
    carrier       VARCHAR(80),
    shipped_on    DATE
);

CREATE TABLE stg_returns (
    id            INTEGER PRIMARY KEY,
    stg_order_id  INTEGER,           -- ORPHAN values (900000+): no overlap with stg_orders.id
    store_id      INTEGER,           -- distractor bait: matches analytics.stores
    reason        VARCHAR(80),
    amount        NUMERIC(12,2)
);

CREATE TABLE stg_suppliers (
    id      INTEGER PRIMARY KEY,
    name    VARCHAR(120),
    status  VARCHAR(24)
);

CREATE TABLE stg_inventory (
    stg_product_id  INTEGER,         -- NO primary key on this table at all
    stg_store_id    INTEGER,
    on_hand         INTEGER,
    counted_at      TIMESTAMPTZ
);

CREATE TABLE stg_employees (
    id      INTEGER PRIMARY KEY,
    name    VARCHAR(160),
    email   VARCHAR(255),
    status  VARCHAR(24)
);

CREATE TABLE stg_web_events (
    id               BIGINT PRIMARY KEY,
    stg_customer_id  INTEGER,
    store_id         INTEGER,        -- distractor bait: matches analytics.stores
    event_type       VARCHAR(40),
    url              VARCHAR(240),
    occurred_at      TIMESTAMPTZ
);

CREATE TABLE stg_promotions (
    id      INTEGER PRIMARY KEY,
    code    VARCHAR(40),
    status  VARCHAR(24)
);

CREATE TABLE stg_exchange_rates (
    currency_code  CHAR(3),          -- no PK
    rate_date      DATE,
    usd_rate       NUMERIC(14,6)
);

-- ============ seed data (value overlap engineered for inference) ============

INSERT INTO stg_customers (id, name, email, status, created_at)
SELECT i, 'Staged Customer ' || i, 'sc' || i || '@example.com',
       (ARRAY['active','inactive'])[1 + i % 2], now() - (i || ' hours')::interval
FROM generate_series(1, 300) i;

INSERT INTO stg_categories (id, name)
SELECT i, 'Staged category ' || i FROM generate_series(1, 12) i;

INSERT INTO stg_products (id, name, stg_category_id, price, status)
SELECT i, 'Staged product ' || i, 1 + (i % 12), round((3 + i % 90)::numeric, 2),
       (ARRAY['active','discontinued'])[1 + i % 2]
FROM generate_series(1, 150) i;

INSERT INTO stg_orders (id, stg_customer_id, status, order_total, created_at)
SELECT i, 1 + (i % 300), (ARRAY['pending','shipped','cancelled'])[1 + i % 3],
       round((10 + i % 500)::numeric, 2), now() - (i || ' hours')::interval
FROM generate_series(1, 600) i;

INSERT INTO stg_order_items (id, stg_order_id, stg_product_id, quantity, unit_price)
SELECT i, 1 + (i % 600), 1 + (i % 150), 1 + (i % 4), round((3 + i % 90)::numeric, 2)
FROM generate_series(1, 1400) i;

INSERT INTO stg_stores (id, name, city)
SELECT i, 'Staged store ' || i, 'City ' || i FROM generate_series(1, 25) i;

INSERT INTO stg_invoices (id, customer_id, amount, status, issued_on)
SELECT i, 1 + (i % 300), round((25 + i % 400)::numeric, 2),
       (ARRAY['open','paid'])[1 + i % 2], DATE '2026-01-01' + (i % 150)
FROM generate_series(1, 250) i;

INSERT INTO stg_payments (id, stg_invoice_id, amount, paid_on)
SELECT i, 1 + (i % 250), round((25 + i % 400)::numeric, 2), DATE '2026-02-01' + (i % 120)
FROM generate_series(1, 200) i;

INSERT INTO stg_shipments (id, stg_order_id, carrier, shipped_on)
SELECT i, (1 + (i % 600))::text, (ARRAY['FedEx','UPS','DHL'])[1 + i % 3], DATE '2026-01-01' + (i % 150)
FROM generate_series(1, 350) i;

INSERT INTO stg_returns (id, stg_order_id, store_id, reason, amount)
SELECT i, 900000 + i, 1 + (i % 25), 'reason ' || (i % 6), round((5 + i % 120)::numeric, 2)
FROM generate_series(1, 120) i;

INSERT INTO stg_suppliers (id, name, status)
SELECT i, 'Staged supplier ' || i, 'active' FROM generate_series(1, 40) i;

INSERT INTO stg_inventory (stg_product_id, stg_store_id, on_hand, counted_at)
SELECT 1 + (i % 150), 1 + (i % 25), (i * 3) % 400, now() - (i || ' minutes')::interval
FROM generate_series(1, 800) i;

INSERT INTO stg_employees (id, name, email, status)
SELECT i, 'Staged employee ' || i, 'se' || i || '@example.com',
       (ARRAY['active','terminated'])[1 + i % 2]
FROM generate_series(1, 90) i;

INSERT INTO stg_web_events (id, stg_customer_id, store_id, event_type, url, occurred_at)
SELECT i, 1 + (i % 300), 1 + (i % 25),
       (ARRAY['page_view','add_to_cart','checkout','search'])[1 + i % 4],
       'https://shop.example.com/p/' || (i % 150), now() - (i || ' minutes')::interval
FROM generate_series(1, 3000) i;

INSERT INTO stg_promotions (id, code, status)
SELECT i, 'SPROMO-' || i, (ARRAY['live','expired'])[1 + i % 2] FROM generate_series(1, 15) i;

INSERT INTO stg_exchange_rates (currency_code, rate_date, usd_rate)
SELECT (ARRAY['EUR','GBP','INR'])[1 + i % 3], DATE '2026-01-01' + (i / 3), round((0.4 + i * 0.01)::numeric, 6)
FROM generate_series(1, 90) i;
