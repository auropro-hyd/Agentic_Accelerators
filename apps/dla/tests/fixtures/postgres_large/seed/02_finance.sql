-- File 02: finance schema — star region #2 (20 tables).
-- Ground truth:
--   * Self-referencing FK: dim_accounts.parent_account_id -> dim_accounts.id.
--   * Composite PKs: dim_fiscal_periods, fact_invoice_lines, purchase_order_lines,
--     exchange_rates.
--   * Multi-column FK: fact_ledger_entries(fiscal_year, fiscal_month) ->
--     dim_fiscal_periods(fiscal_year, fiscal_month).
--   * Cross-schema declared FK: expense_reports.employee_id -> hr.employees(id)
--     (added in 03_hr.sql after hr.employees exists).
--   * Junctions: invoice_payments, vendor_contract_links.
--   * Star facts: fact_invoices, fact_payments, fact_ledger_entries, fact_budgets.
--   * Text-heavy: audit_journal.narrative.

SET client_min_messages = WARNING;
SET search_path = finance;

CREATE TABLE dim_accounts (
    id                 SERIAL PRIMARY KEY,
    account_code       VARCHAR(20) NOT NULL UNIQUE,
    name               VARCHAR(120) NOT NULL,
    account_type       VARCHAR(20) NOT NULL,
    parent_account_id  INTEGER REFERENCES dim_accounts(id)     -- self-referencing FK
);

CREATE TABLE dim_cost_centers (
    id       SERIAL PRIMARY KEY,
    code     VARCHAR(16) NOT NULL UNIQUE,
    name     VARCHAR(120) NOT NULL,
    manager  VARCHAR(120)
);

CREATE TABLE dim_vendors (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(160) NOT NULL,
    tax_id      VARCHAR(32),
    country     CHAR(2),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dim_gl_codes (
    id           SERIAL PRIMARY KEY,
    gl_code      VARCHAR(12) NOT NULL UNIQUE,
    description  VARCHAR(200)
);

CREATE TABLE dim_fiscal_periods (
    fiscal_year   SMALLINT NOT NULL,
    fiscal_month  SMALLINT NOT NULL,
    starts_on     DATE NOT NULL,
    ends_on       DATE NOT NULL,
    is_closed     BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (fiscal_year, fiscal_month)                    -- composite PK
);

CREATE TABLE fact_invoices (
    id              SERIAL PRIMARY KEY,
    invoice_number  VARCHAR(32) NOT NULL UNIQUE,
    vendor_id       INTEGER NOT NULL REFERENCES dim_vendors(id),
    cost_center_id  INTEGER NOT NULL REFERENCES dim_cost_centers(id),
    issued_on       DATE NOT NULL,
    due_on          DATE NOT NULL,
    status          VARCHAR(24) NOT NULL,
    subtotal        NUMERIC(14,2) NOT NULL,
    tax             NUMERIC(14,2) NOT NULL DEFAULT 0,
    total           NUMERIC(14,2) NOT NULL
);

CREATE TABLE fact_invoice_lines (
    invoice_id   INTEGER NOT NULL REFERENCES fact_invoices(id) ON DELETE CASCADE,
    line_no      SMALLINT NOT NULL,
    gl_code_id   INTEGER NOT NULL REFERENCES dim_gl_codes(id),
    description  VARCHAR(240),
    quantity     NUMERIC(10,2) NOT NULL DEFAULT 1,
    unit_cost    NUMERIC(12,2) NOT NULL,
    amount       NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (invoice_id, line_no)                          -- composite PK
);

CREATE TABLE fact_payments (
    id              SERIAL PRIMARY KEY,
    payment_ref     VARCHAR(32) NOT NULL UNIQUE,
    vendor_id       INTEGER NOT NULL REFERENCES dim_vendors(id),
    account_id      INTEGER NOT NULL REFERENCES dim_accounts(id),
    paid_on         DATE NOT NULL,
    amount          NUMERIC(14,2) NOT NULL,
    method          VARCHAR(24) NOT NULL
);

-- Junction: invoices <-> payments (partial payments, batch payments)
CREATE TABLE invoice_payments (
    invoice_id  INTEGER NOT NULL REFERENCES fact_invoices(id),
    payment_id  INTEGER NOT NULL REFERENCES fact_payments(id),
    applied     NUMERIC(14,2),
    PRIMARY KEY (invoice_id, payment_id)
);

CREATE TABLE fact_ledger_entries (
    id              BIGSERIAL PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES dim_accounts(id),
    cost_center_id  INTEGER NOT NULL REFERENCES dim_cost_centers(id),
    fiscal_year     SMALLINT NOT NULL,
    fiscal_month    SMALLINT NOT NULL,
    entry_date      DATE NOT NULL,
    debit           NUMERIC(14,2) NOT NULL DEFAULT 0,
    credit          NUMERIC(14,2) NOT NULL DEFAULT 0,
    memo            VARCHAR(240),
    FOREIGN KEY (fiscal_year, fiscal_month)                    -- multi-column FK
        REFERENCES dim_fiscal_periods(fiscal_year, fiscal_month)
);

CREATE TABLE fact_budgets (
    id              SERIAL PRIMARY KEY,
    cost_center_id  INTEGER NOT NULL REFERENCES dim_cost_centers(id),
    account_id      INTEGER NOT NULL REFERENCES dim_accounts(id),
    fiscal_year     SMALLINT NOT NULL,
    amount          NUMERIC(14,2) NOT NULL
);

CREATE TABLE tax_rates (
    id           SERIAL PRIMARY KEY,
    jurisdiction VARCHAR(80) NOT NULL,
    rate_pct     NUMERIC(6,3) NOT NULL,
    valid_from   DATE NOT NULL
);

CREATE TABLE exchange_rates (
    currency_code  CHAR(3) NOT NULL,
    rate_date      DATE NOT NULL,
    usd_rate       NUMERIC(14,6) NOT NULL,
    PRIMARY KEY (currency_code, rate_date)                     -- composite PK
);

CREATE TABLE purchase_orders (
    id           SERIAL PRIMARY KEY,
    po_number    VARCHAR(24) NOT NULL UNIQUE,
    vendor_id    INTEGER NOT NULL REFERENCES dim_vendors(id),
    ordered_on   DATE NOT NULL,
    status       VARCHAR(24) NOT NULL,
    total        NUMERIC(14,2)
);

CREATE TABLE purchase_order_lines (
    po_id      INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    line_no    SMALLINT NOT NULL,
    item_desc  VARCHAR(240) NOT NULL,
    quantity   NUMERIC(10,2) NOT NULL,
    unit_cost  NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (po_id, line_no)
);

CREATE TABLE vendor_contracts (
    id          SERIAL PRIMARY KEY,
    vendor_id   INTEGER NOT NULL REFERENCES dim_vendors(id),
    starts_on   DATE NOT NULL,
    ends_on     DATE,
    terms       TEXT
);

-- Junction: contracts <-> cost centers that draw on them
CREATE TABLE vendor_contract_links (
    contract_id     INTEGER NOT NULL REFERENCES vendor_contracts(id),
    cost_center_id  INTEGER NOT NULL REFERENCES dim_cost_centers(id),
    PRIMARY KEY (contract_id, cost_center_id)
);

CREATE TABLE expense_reports (
    id           SERIAL PRIMARY KEY,
    employee_id  INTEGER NOT NULL,           -- FK to hr.employees added in 03_hr.sql
    submitted_on DATE NOT NULL,
    status       VARCHAR(24) NOT NULL,
    total        NUMERIC(12,2) NOT NULL
);

CREATE TABLE expense_lines (
    id          SERIAL PRIMARY KEY,
    report_id   INTEGER NOT NULL REFERENCES expense_reports(id) ON DELETE CASCADE,
    category    VARCHAR(40) NOT NULL,
    amount      NUMERIC(12,2) NOT NULL,
    receipt_url VARCHAR(240)
);

CREATE TABLE payment_batches (
    id          SERIAL PRIMARY KEY,
    batch_ref   VARCHAR(32) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE audit_journal (
    id          BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       VARCHAR(120) NOT NULL,
    action      VARCHAR(80) NOT NULL,
    narrative   TEXT NOT NULL,
    details     JSONB
);

-- ============ seed data ============

INSERT INTO dim_accounts (account_code, name, account_type, parent_account_id) VALUES
    ('1000', 'Assets', 'asset', NULL),
    ('1100', 'Cash', 'asset', 1),
    ('1200', 'Receivables', 'asset', 1),
    ('2000', 'Liabilities', 'liability', NULL),
    ('2100', 'Payables', 'liability', 4),
    ('4000', 'Revenue', 'revenue', NULL),
    ('4100', 'Product revenue', 'revenue', 6),
    ('5000', 'Expenses', 'expense', NULL),
    ('5100', 'Freight', 'expense', 8),
    ('5200', 'Payroll', 'expense', 8);

INSERT INTO dim_cost_centers (code, name, manager)
SELECT 'CC-' || lpad(i::text, 3, '0'), 'Cost center ' || i, 'Manager ' || i
FROM generate_series(1, 12) i;

INSERT INTO dim_vendors (name, tax_id, country)
SELECT 'Vendor ' || i, 'TAX-' || lpad(i::text, 6, '0'), (ARRAY['US','GB','DE','IN'])[1 + i % 4]
FROM generate_series(1, 60) i;

INSERT INTO dim_gl_codes (gl_code, description)
SELECT 'GL-' || lpad(i::text, 4, '0'), 'General ledger code ' || i
FROM generate_series(1, 25) i;

INSERT INTO dim_fiscal_periods (fiscal_year, fiscal_month, starts_on, ends_on, is_closed)
SELECT y, m, make_date(y, m, 1), (make_date(y, m, 1) + interval '1 month - 1 day')::date, y = 2025
FROM generate_series(2025, 2026) y, generate_series(1, 12) m;

INSERT INTO fact_invoices (invoice_number, vendor_id, cost_center_id, issued_on, due_on, status, subtotal, tax, total)
SELECT 'INV-' || lpad(i::text, 6, '0'), 1 + (i % 60), 1 + (i % 12),
       DATE '2025-01-05' + i, DATE '2025-02-05' + i,
       (ARRAY['draft','approved','paid','void'])[1 + i % 4],
       round((100 + i * 3)::numeric, 2), round(((100 + i * 3) * 0.18)::numeric, 2),
       round(((100 + i * 3) * 1.18)::numeric, 2)
FROM generate_series(1, 400) i;

INSERT INTO fact_invoice_lines (invoice_id, line_no, gl_code_id, description, quantity, unit_cost, amount)
SELECT 1 + (i / 3), 1 + (i % 3), 1 + (i % 25), 'Line item ' || i, 1 + (i % 4),
       round((20 + i % 300)::numeric, 2), round(((20 + i % 300) * (1 + i % 4))::numeric, 2)
FROM generate_series(0, 1100) i;

INSERT INTO fact_payments (payment_ref, vendor_id, account_id, paid_on, amount, method)
SELECT 'PAY-' || lpad(i::text, 6, '0'), 1 + (i % 60), 2, DATE '2025-02-01' + i,
       round((100 + i * 2.7)::numeric, 2), (ARRAY['ach','wire','check'])[1 + i % 3]
FROM generate_series(1, 300) i;

INSERT INTO invoice_payments (invoice_id, payment_id, applied)
SELECT 1 + (i % 400), 1 + (i % 300), round((50 + i)::numeric, 2)
FROM generate_series(1, 350) i
ON CONFLICT DO NOTHING;

INSERT INTO fact_ledger_entries (account_id, cost_center_id, fiscal_year, fiscal_month, entry_date, debit, credit, memo)
SELECT 1 + (i % 10), 1 + (i % 12), 2025 + (i % 2), 1 + (i % 12),
       make_date(2025 + (i % 2), 1 + (i % 12), 1 + (i % 28)),
       CASE WHEN i % 2 = 0 THEN round((10 + i % 900)::numeric, 2) ELSE 0 END,
       CASE WHEN i % 2 = 1 THEN round((10 + i % 900)::numeric, 2) ELSE 0 END,
       'Journal memo ' || i
FROM generate_series(1, 2000) i;

INSERT INTO fact_budgets (cost_center_id, account_id, fiscal_year, amount)
SELECT c, a, y, 50000 + c * 100 + a * 10
FROM generate_series(1, 12) c, generate_series(1, 10) a, generate_series(2025, 2026) y;

INSERT INTO tax_rates (jurisdiction, rate_pct, valid_from)
SELECT 'Jurisdiction ' || i, round((5 + i % 15)::numeric, 3), DATE '2024-01-01' + i * 7
FROM generate_series(1, 15) i;

INSERT INTO exchange_rates (currency_code, rate_date, usd_rate)
SELECT c, DATE '2026-01-01' + d, round((0.5 + random() * 90)::numeric, 6)
FROM unnest(ARRAY['EUR','GBP','INR','JPY']) c, generate_series(0, 120) d;

INSERT INTO purchase_orders (po_number, vendor_id, ordered_on, status, total)
SELECT 'PO-' || lpad(i::text, 5, '0'), 1 + (i % 60), DATE '2025-03-01' + i,
       (ARRAY['open','received','closed'])[1 + i % 3], round((500 + i * 11)::numeric, 2)
FROM generate_series(1, 150) i;

INSERT INTO purchase_order_lines (po_id, line_no, item_desc, quantity, unit_cost)
SELECT 1 + (i / 2), 1 + (i % 2), 'PO line ' || i, 1 + (i % 9), round((15 + i % 400)::numeric, 2)
FROM generate_series(0, 280) i;

INSERT INTO vendor_contracts (vendor_id, starts_on, ends_on, terms)
SELECT 1 + (i % 60), DATE '2024-01-01' + i * 5, DATE '2026-01-01' + i * 5,
       'Net 45 payment terms with a two percent early-settlement discount when paid within ten '
       || 'days. Renewal is automatic unless either party gives ninety days written notice. '
       || 'Service credits accrue when monthly uptime falls below the agreed threshold. Contract ' || i
FROM generate_series(1, 45) i;

INSERT INTO vendor_contract_links (contract_id, cost_center_id)
SELECT 1 + (i % 45), 1 + (i % 12) FROM generate_series(1, 60) i
ON CONFLICT DO NOTHING;

INSERT INTO expense_reports (employee_id, submitted_on, status, total)
SELECT 1 + (i % 120), DATE '2026-01-10' + i, (ARRAY['submitted','approved','reimbursed'])[1 + i % 3],
       round((40 + i * 3)::numeric, 2)
FROM generate_series(1, 90) i;

INSERT INTO expense_lines (report_id, category, amount, receipt_url)
SELECT 1 + (i % 90), (ARRAY['travel','meals','lodging','supplies'])[1 + i % 4],
       round((10 + i % 250)::numeric, 2), 'https://receipts.example.com/' || i
FROM generate_series(1, 200) i;

INSERT INTO payment_batches (batch_ref, row_count)
SELECT 'BATCH-' || lpad(i::text, 4, '0'), 10 + i FROM generate_series(1, 25) i;

INSERT INTO audit_journal (actor, action, narrative, details)
SELECT 'clerk_' || (1 + i % 8), (ARRAY['post','reverse','approve'])[1 + i % 3],
       'Period-end adjustment posted after reconciling the vendor statement against open '
       || 'payables. Two invoices required manual matching because the vendor combined several '
       || 'purchase orders into a single statement line. Supporting evidence is attached to the '
       || 'workflow ticket and the reviewer signed off on the variance explanation. Entry ' || i,
       jsonb_build_object('ticket', 'FIN-' || i, 'variance', (i % 50))
FROM generate_series(1, 120) i;
