-- File 01: sales schema — star + snowflake region #1 (26 tables).
-- Ground truth:
--   * Star facts: fact_sales, fact_returns, fact_shipments, fact_inventory_snapshots
--     (each references >= 2 dims and carries its own measures). product_reviews and
--     customer_notes also satisfy the detector's fact shape (>=2 FK targets + extra
--     columns) even though they are semantically text tables.
--   * Snowflake chains: dim_products -> dim_subcategories -> dim_categories ->
--     dim_departments; dim_stores -> dim_regions -> dim_countries -> dim_continents.
--   * Junctions: bridge_product_suppliers, bridge_customer_segments,
--     bridge_promotion_channels.
--   * Conformed dims shared across all four facts: dim_date, dim_stores, dim_products.
--   * Text-heavy (vector signal): product_reviews.review_text, customer_notes.body.

SET client_min_messages = WARNING;
SET search_path = sales;

-- ============ snowflake outer layers (created first for FK ordering) ============

CREATE TABLE dim_departments (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(80) NOT NULL UNIQUE
);

CREATE TABLE dim_categories (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(80) NOT NULL,
    department_id  INTEGER NOT NULL REFERENCES dim_departments(id)
);

CREATE TABLE dim_subcategories (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(80) NOT NULL,
    category_id  INTEGER NOT NULL REFERENCES dim_categories(id)
);

CREATE TABLE dim_continents (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(40) NOT NULL UNIQUE
);

CREATE TABLE dim_countries (
    id            SERIAL PRIMARY KEY,
    iso_code      CHAR(2) NOT NULL UNIQUE,
    name          VARCHAR(80) NOT NULL,
    continent_id  INTEGER NOT NULL REFERENCES dim_continents(id)
);

CREATE TABLE dim_regions (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(80) NOT NULL,
    country_id  INTEGER NOT NULL REFERENCES dim_countries(id)
);

-- ============ conformed dimensions ============

CREATE TABLE dim_date (
    date_key     INTEGER PRIMARY KEY,          -- yyyymmdd
    full_date    DATE NOT NULL UNIQUE,
    year         SMALLINT NOT NULL,
    quarter      SMALLINT NOT NULL,
    month        SMALLINT NOT NULL,
    day_of_week  SMALLINT NOT NULL,
    is_weekend   BOOLEAN NOT NULL
);

CREATE TABLE dim_customers (
    id            SERIAL PRIMARY KEY,
    customer_code VARCHAR(24) NOT NULL UNIQUE,
    full_name     VARCHAR(160) NOT NULL,
    email         VARCHAR(255),
    signed_up_on  DATE NOT NULL,
    loyalty_tier  VARCHAR(16) NOT NULL DEFAULT 'bronze',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dim_products (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(40) NOT NULL UNIQUE,
    name            VARCHAR(160) NOT NULL,
    subcategory_id  INTEGER NOT NULL REFERENCES dim_subcategories(id),
    list_price      NUMERIC(10,2) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dim_stores (
    id          SERIAL PRIMARY KEY,
    store_code  VARCHAR(16) NOT NULL UNIQUE,
    name        VARCHAR(120) NOT NULL,
    region_id   INTEGER NOT NULL REFERENCES dim_regions(id),
    opened_on   DATE NOT NULL,
    sq_meters   INTEGER
);

CREATE TABLE dim_channels (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(40) NOT NULL UNIQUE
);

CREATE TABLE dim_promotions (
    id            SERIAL PRIMARY KEY,
    code          VARCHAR(40) NOT NULL UNIQUE,
    description   TEXT,
    discount_pct  NUMERIC(5,2) NOT NULL,
    valid_from    DATE NOT NULL,
    valid_to      DATE NOT NULL
);

CREATE TABLE dim_payment_methods (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(40) NOT NULL UNIQUE
);

CREATE TABLE dim_currencies (
    code       CHAR(3) PRIMARY KEY,
    name       VARCHAR(40) NOT NULL,
    symbol     VARCHAR(4)
);

-- ============ support tables ============

CREATE TABLE suppliers (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(120) NOT NULL,
    country_id   INTEGER REFERENCES dim_countries(id),
    rating       NUMERIC(3,1),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE segments (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(80) NOT NULL UNIQUE,
    description  TEXT
);

-- ============ junction / bridge tables ============

CREATE TABLE bridge_product_suppliers (
    product_id   INTEGER NOT NULL REFERENCES dim_products(id),
    supplier_id  INTEGER NOT NULL REFERENCES suppliers(id),
    since        DATE,
    PRIMARY KEY (product_id, supplier_id)
);

CREATE TABLE bridge_customer_segments (
    customer_id  INTEGER NOT NULL REFERENCES dim_customers(id),
    segment_id   INTEGER NOT NULL REFERENCES segments(id),
    PRIMARY KEY (customer_id, segment_id)
);

CREATE TABLE bridge_promotion_channels (
    promotion_id  INTEGER NOT NULL REFERENCES dim_promotions(id),
    channel_id    INTEGER NOT NULL REFERENCES dim_channels(id),
    PRIMARY KEY (promotion_id, channel_id)
);

-- ============ facts ============

CREATE TABLE fact_sales (
    id                 BIGSERIAL PRIMARY KEY,
    date_key           INTEGER NOT NULL REFERENCES dim_date(date_key),
    customer_id        INTEGER NOT NULL REFERENCES dim_customers(id),
    product_id         INTEGER NOT NULL REFERENCES dim_products(id),
    store_id           INTEGER NOT NULL REFERENCES dim_stores(id),
    channel_id         INTEGER NOT NULL REFERENCES dim_channels(id),
    promotion_id       INTEGER REFERENCES dim_promotions(id),
    payment_method_id  INTEGER NOT NULL REFERENCES dim_payment_methods(id),
    currency_code      CHAR(3) NOT NULL REFERENCES dim_currencies(code),
    quantity           INTEGER NOT NULL CHECK (quantity > 0),
    unit_price         NUMERIC(10,2) NOT NULL,
    discount_amount    NUMERIC(10,2) NOT NULL DEFAULT 0,
    tax_amount         NUMERIC(10,2) NOT NULL DEFAULT 0,
    net_amount         NUMERIC(12,2) NOT NULL
);
CREATE INDEX idx_fact_sales_date     ON fact_sales(date_key);
CREATE INDEX idx_fact_sales_customer ON fact_sales(customer_id);
CREATE INDEX idx_fact_sales_product  ON fact_sales(product_id);

CREATE TABLE fact_returns (
    id           BIGSERIAL PRIMARY KEY,
    date_key     INTEGER NOT NULL REFERENCES dim_date(date_key),
    customer_id  INTEGER NOT NULL REFERENCES dim_customers(id),
    product_id   INTEGER NOT NULL REFERENCES dim_products(id),
    store_id     INTEGER NOT NULL REFERENCES dim_stores(id),
    reason       sales.return_reason NOT NULL,
    quantity     INTEGER NOT NULL,
    amount       NUMERIC(12,2) NOT NULL
);

CREATE TABLE fact_shipments (
    id            BIGSERIAL PRIMARY KEY,
    date_key      INTEGER NOT NULL REFERENCES dim_date(date_key),
    store_id      INTEGER NOT NULL REFERENCES dim_stores(id),
    product_id    INTEGER NOT NULL REFERENCES dim_products(id),
    cartons       INTEGER NOT NULL,
    weight_kg     NUMERIC(10,3),
    freight_cost  NUMERIC(12,2)
);

CREATE TABLE fact_inventory_snapshots (
    date_key    INTEGER NOT NULL REFERENCES dim_date(date_key),
    product_id  INTEGER NOT NULL REFERENCES dim_products(id),
    store_id    INTEGER NOT NULL REFERENCES dim_stores(id),
    on_hand     INTEGER NOT NULL,
    reserved    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date_key, product_id, store_id)      -- composite PK, no surrogate
);

-- ============ text-heavy tables (vector signal) ============

CREATE TABLE product_reviews (
    id           SERIAL PRIMARY KEY,
    product_id   INTEGER NOT NULL REFERENCES dim_products(id),
    customer_id  INTEGER NOT NULL REFERENCES dim_customers(id),
    rating       SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_text  TEXT NOT NULL,
    reviewed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE customer_notes (
    id           SERIAL PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES dim_customers(id),
    author       VARCHAR(80) NOT NULL,
    body         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Composite-PK planning table (no surrogate key)
CREATE TABLE sales_targets (
    store_id       INTEGER NOT NULL REFERENCES dim_stores(id),
    fiscal_year    SMALLINT NOT NULL,
    fiscal_quarter SMALLINT NOT NULL,
    target_amount  NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (store_id, fiscal_year, fiscal_quarter)
);

-- ============ seed data ============

INSERT INTO dim_departments (name) VALUES ('Softlines'), ('Hardlines'), ('Grocery');
INSERT INTO dim_categories (name, department_id) VALUES
    ('Apparel', 1), ('Footwear', 1), ('Electronics', 2), ('Home', 2), ('Snacks', 3), ('Beverages', 3);
INSERT INTO dim_subcategories (name, category_id)
SELECT c.name || ' - sub ' || s, c.id FROM dim_categories c, generate_series(1, 3) s;

INSERT INTO dim_continents (name) VALUES ('Europe'), ('North America'), ('Asia');
INSERT INTO dim_countries (iso_code, name, continent_id) VALUES
    ('GB', 'United Kingdom', 1), ('DE', 'Germany', 1), ('US', 'United States', 2),
    ('CA', 'Canada', 2), ('IN', 'India', 3), ('JP', 'Japan', 3);
INSERT INTO dim_regions (name, country_id)
SELECT c.name || ' region ' || s, c.id FROM dim_countries c, generate_series(1, 2) s;

INSERT INTO dim_date (date_key, full_date, year, quarter, month, day_of_week, is_weekend)
SELECT to_char(d, 'YYYYMMDD')::int, d::date,
       EXTRACT(year FROM d)::smallint, EXTRACT(quarter FROM d)::smallint,
       EXTRACT(month FROM d)::smallint, EXTRACT(isodow FROM d)::smallint,
       EXTRACT(isodow FROM d) IN (6, 7)
FROM generate_series('2025-01-01'::date, '2026-06-30'::date, interval '1 day') d;

INSERT INTO dim_customers (customer_code, full_name, email, signed_up_on, loyalty_tier)
SELECT 'CUST-' || lpad(i::text, 5, '0'),
       'Customer ' || i,
       'customer' || i || '@example.com',
       DATE '2025-01-01' + (i % 500),
       (ARRAY['bronze','silver','gold'])[1 + i % 3]
FROM generate_series(1, 400) i;

INSERT INTO dim_products (sku, name, subcategory_id, list_price)
SELECT 'SKU-' || lpad(i::text, 5, '0'),
       'Product ' || i,
       1 + (i % 18),
       round((5 + random() * 195)::numeric, 2)
FROM generate_series(1, 250) i;

INSERT INTO dim_stores (store_code, name, region_id, opened_on, sq_meters)
SELECT 'ST-' || lpad(i::text, 3, '0'),
       'Store ' || i,
       1 + (i % 12),
       DATE '2020-01-01' + (i * 30),
       400 + (i * 25)
FROM generate_series(1, 40) i;

INSERT INTO dim_channels (name) VALUES ('in_store'), ('web'), ('mobile_app'), ('marketplace');
INSERT INTO dim_promotions (code, description, discount_pct, valid_from, valid_to)
SELECT 'PROMO-' || i, 'Promotion number ' || i, 5 + (i % 4) * 5,
       DATE '2025-01-01' + i * 10, DATE '2025-01-01' + i * 10 + 30
FROM generate_series(1, 20) i;
INSERT INTO dim_payment_methods (name) VALUES ('card'), ('cash'), ('wallet'), ('bank_transfer');
INSERT INTO dim_currencies (code, name, symbol) VALUES
    ('USD', 'US Dollar', '$'), ('EUR', 'Euro', E'€'), ('GBP', 'Pound Sterling', E'£'), ('INR', 'Indian Rupee', E'₹');

INSERT INTO suppliers (name, country_id, rating)
SELECT 'Supplier ' || i, 1 + (i % 6), round((1 + random() * 4)::numeric, 1)
FROM generate_series(1, 30) i;

INSERT INTO segments (name, description) VALUES
    ('high_value', 'Top decile of lifetime spend'),
    ('lapsed', 'No purchase in 180 days'),
    ('new', 'First purchase within 30 days'),
    ('promo_hunter', 'Purchases predominantly on promotion');

INSERT INTO bridge_product_suppliers (product_id, supplier_id, since)
SELECT i, 1 + (i % 30), DATE '2024-01-01' + i FROM generate_series(1, 250) i;
INSERT INTO bridge_product_suppliers (product_id, supplier_id, since)
SELECT i, 1 + ((i + 7) % 30), DATE '2024-06-01' + i FROM generate_series(1, 120) i;

INSERT INTO bridge_customer_segments (customer_id, segment_id)
SELECT i, 1 + (i % 4) FROM generate_series(1, 400) i;

INSERT INTO bridge_promotion_channels (promotion_id, channel_id)
SELECT p, c FROM generate_series(1, 20) p, generate_series(1, 4) c WHERE (p + c) % 2 = 0;

INSERT INTO fact_sales (date_key, customer_id, product_id, store_id, channel_id,
                        promotion_id, payment_method_id, currency_code,
                        quantity, unit_price, discount_amount, tax_amount, net_amount)
SELECT (SELECT date_key FROM dim_date ORDER BY date_key OFFSET (i % 540) LIMIT 1),
       1 + (i % 400),
       1 + (i % 250),
       1 + (i % 40),
       1 + (i % 4),
       CASE WHEN i % 5 = 0 THEN 1 + (i % 20) END,
       1 + (i % 4),
       (ARRAY['USD','EUR','GBP','INR'])[1 + i % 4],
       1 + (i % 5),
       round((5 + (i % 200))::numeric, 2),
       CASE WHEN i % 5 = 0 THEN 2.50 ELSE 0 END,
       round(((5 + (i % 200)) * 0.08)::numeric, 2),
       round(((5 + (i % 200)) * 1.08 * (1 + i % 5))::numeric, 2)
FROM generate_series(1, 5000) i;

INSERT INTO fact_returns (date_key, customer_id, product_id, store_id, reason, quantity, amount)
SELECT (SELECT date_key FROM dim_date ORDER BY date_key OFFSET (i % 540) LIMIT 1),
       1 + (i % 400), 1 + (i % 250), 1 + (i % 40),
       (ARRAY['damaged','wrong_item','too_late','changed_mind'])[1 + i % 4]::sales.return_reason,
       1, round((5 + (i % 120))::numeric, 2)
FROM generate_series(1, 300) i;

INSERT INTO fact_shipments (date_key, store_id, product_id, cartons, weight_kg, freight_cost)
SELECT (SELECT date_key FROM dim_date ORDER BY date_key OFFSET (i % 540) LIMIT 1),
       1 + (i % 40), 1 + (i % 250), 1 + (i % 12),
       round((0.5 + (i % 90))::numeric, 3), round((10 + (i % 300))::numeric, 2)
FROM generate_series(1, 800) i;

INSERT INTO fact_inventory_snapshots (date_key, product_id, store_id, on_hand, reserved)
SELECT (SELECT date_key FROM dim_date ORDER BY date_key OFFSET (i % 30) LIMIT 1),
       1 + (i % 250), 1 + ((i / 250) % 40), (i * 7) % 500, (i * 3) % 40
FROM generate_series(0, 1999) i;

INSERT INTO product_reviews (product_id, customer_id, rating, review_text)
SELECT 1 + (i % 250), 1 + (i % 400), 1 + (i % 5),
       'I have been using this product for ' || (1 + i % 11) || ' weeks now and the build quality '
       || 'continues to impress me. The finish feels premium, delivery was quick, and the '
       || 'packaging was thoughtful. My only complaint is that the instruction booklet is vague '
       || 'about maintenance, so I had to search online forums for cleaning advice. Overall I '
       || 'would recommend it to a friend who cares about durability more than price. Review #' || i
FROM generate_series(1, 350) i;

INSERT INTO customer_notes (customer_id, author, body)
SELECT 1 + (i % 400), 'agent_' || (1 + i % 12),
       'Spoke with the customer about their recent delivery delay. They were understanding but '
       || 'asked to be notified proactively next time a shipment slips. Flagged the account for '
       || 'the loyalty win-back campaign and promised a follow-up call within five business days. '
       || 'Customer prefers email over phone for routine updates. Interaction log entry ' || i
FROM generate_series(1, 200) i;

INSERT INTO sales_targets (store_id, fiscal_year, fiscal_quarter, target_amount)
SELECT s, y, q, 100000 + s * 1000 + q * 500
FROM generate_series(1, 40) s, generate_series(2025, 2026) y, generate_series(1, 4) q;
