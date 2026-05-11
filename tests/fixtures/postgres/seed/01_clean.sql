-- 12-table retail fixture: clean schema with declared FKs, indexes, audit columns,
-- a junction table, and a self-contained audit_log. Used by M1 discovery demo
-- and M2 profiling. Data volume is deliberately small (under 100 rows total)
-- so re-runs are fast and the bundle reads naturally during the demo.

SET client_min_messages = WARNING;

-- ============================================================
-- Lookup / dimension tables
-- ============================================================

CREATE TABLE categories (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(80) NOT NULL UNIQUE,
    description  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id           SERIAL PRIMARY KEY,
    sku          VARCHAR(40) NOT NULL UNIQUE,
    name         VARCHAR(160) NOT NULL,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    list_price   NUMERIC(10,2) NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_products_category ON products(category_id);

CREATE TABLE customers (
    id           SERIAL PRIMARY KEY,
    email        VARCHAR(255) NOT NULL UNIQUE,
    full_name    VARCHAR(160) NOT NULL,
    signed_up_on DATE NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE addresses (
    id           SERIAL PRIMARY KEY,
    line1        VARCHAR(160) NOT NULL,
    line2        VARCHAR(160),
    city         VARCHAR(80) NOT NULL,
    region       VARCHAR(80),
    postal_code  VARCHAR(20) NOT NULL,
    country_code CHAR(2) NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Junction: customer ↔ address (many-to-many with label)
CREATE TABLE customer_addresses (
    customer_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    address_id   INTEGER NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    label        VARCHAR(20) NOT NULL,
    is_default   BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (customer_id, address_id, label)
);

-- ============================================================
-- Transactional tables
-- ============================================================

CREATE TABLE orders (
    id            SERIAL PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(id),
    status        VARCHAR(32) NOT NULL,
    placed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_amount  NUMERIC(12,2) NOT NULL DEFAULT 0,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_status   ON orders(status);

CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(10,2) NOT NULL,
    UNIQUE (order_id, product_id)
);

CREATE TABLE shipments (
    id              SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(id),
    shipped_at      TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    carrier         VARCHAR(80),
    tracking_number VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE inventory (
    id           SERIAL PRIMARY KEY,
    product_id   INTEGER NOT NULL UNIQUE REFERENCES products(id),
    on_hand      INTEGER NOT NULL DEFAULT 0,
    reserved     INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- Promotions: another junction example
-- ============================================================

CREATE TABLE promotions (
    id            SERIAL PRIMARY KEY,
    code          VARCHAR(40) NOT NULL UNIQUE,
    description   TEXT,
    discount_pct  NUMERIC(5,2) NOT NULL,
    valid_from    DATE NOT NULL,
    valid_to      DATE NOT NULL
);

CREATE TABLE customer_promotions (
    customer_id   INTEGER NOT NULL REFERENCES customers(id),
    promotion_id  INTEGER NOT NULL REFERENCES promotions(id),
    redeemed_at   TIMESTAMPTZ,
    PRIMARY KEY (customer_id, promotion_id)
);

-- ============================================================
-- Audit (standalone, no FKs)
-- ============================================================

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       VARCHAR(120) NOT NULL,
    action      VARCHAR(80) NOT NULL,
    entity_type VARCHAR(80) NOT NULL,
    entity_id   VARCHAR(120) NOT NULL,
    details     JSONB
);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);

-- ============================================================
-- Seed data (small — keeps re-runs fast)
-- ============================================================

INSERT INTO categories (name, description) VALUES
    ('Apparel',     'Clothing and accessories'),
    ('Electronics', 'Consumer electronics'),
    ('Home',        'Home goods');

INSERT INTO products (sku, name, category_id, list_price) VALUES
    ('A-001', 'Cotton t-shirt',    1, 19.99),
    ('A-002', 'Denim jeans',       1, 49.50),
    ('E-001', 'Bluetooth speaker', 2, 89.00),
    ('H-001', 'Linen napkin set',  3, 24.00);

INSERT INTO customers (email, full_name, signed_up_on) VALUES
    ('alice@example.com', 'Alice Hartwell', '2025-03-12'),
    ('bob@example.com',   'Bob Iyer',       '2025-06-04'),
    ('cara@example.com',  'Cara Mendez',    '2026-01-21');

INSERT INTO addresses (line1, city, postal_code, country_code) VALUES
    ('221B Baker St', 'London',   'NW1 6XE', 'GB'),
    ('1 Infinite Loop', 'Cupertino', '95014', 'US');

INSERT INTO customer_addresses (customer_id, address_id, label, is_default) VALUES
    (1, 1, 'shipping', TRUE),
    (2, 2, 'shipping', TRUE);

INSERT INTO orders (customer_id, status, total_amount) VALUES
    (1, 'shipped',   69.49),
    (2, 'pending',   89.00),
    (1, 'cancelled', 0.00);

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 1, 19.99),
    (1, 2, 1, 49.50),
    (2, 3, 1, 89.00);

INSERT INTO shipments (order_id, shipped_at, carrier, tracking_number) VALUES
    (1, now() - interval '2 days', 'FedEx', 'FX1234');

INSERT INTO inventory (product_id, on_hand) VALUES
    (1, 120), (2, 60), (3, 12), (4, 200);

INSERT INTO promotions (code, description, discount_pct, valid_from, valid_to) VALUES
    ('WELCOME10', 'New customer 10% off', 10.00, '2026-01-01', '2026-12-31');

INSERT INTO customer_promotions (customer_id, promotion_id, redeemed_at) VALUES
    (3, 1, now() - interval '5 days');

INSERT INTO audit_log (actor, action, entity_type, entity_id, details) VALUES
    ('system', 'create', 'order', '1', '{"reason":"initial seed"}'::jsonb);
