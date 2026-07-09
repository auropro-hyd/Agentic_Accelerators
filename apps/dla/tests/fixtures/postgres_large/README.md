# Large synthetic Postgres fixture (125 tables, 5 schemas)

A stress-test fixture for exercising every documented `dla` capability at
realistic scale. It complements — and never replaces — the small demo fixture in
`../postgres/` (which stays on port 55432).

```bash
docker compose -f apps/dla/tests/fixtures/postgres_large/docker-compose.yaml up -d
docker exec dla_fixture_postgres_large pg_isready -U dla -d dla_fixture_large
export DLA_DB_PASSWORD=dla_dev_password
```

- Host port: **55433** (container `dla_fixture_postgres_large`)
- Database: `dla_fixture_large`, user `dla`, password `dla_dev_password`
- Total: **125 tables**, ~130k rows (one deliberately tall 100k-row table)

## Regions

| Schema | Tables | What it stresses |
| ------ | ------ | ---------------- |
| `sales` | 26 | Star #1: 4 facts sharing conformed dims (`dim_date`, `dim_products`, `dim_stores`); two snowflake chains (`dim_products→dim_subcategories→dim_categories→dim_departments`, `dim_stores→dim_regions→dim_countries→dim_continents`); 3 bridge tables; text-heavy `product_reviews` / `customer_notes`; composite-PK `fact_inventory_snapshots` and `sales_targets`. |
| `finance` | 21 | Star #2; self-referencing `dim_accounts.parent_account_id`; composite PKs (`dim_fiscal_periods`, `fact_invoice_lines`, `purchase_order_lines`, `exchange_rates`); **multi-column FK** `fact_ledger_entries(fiscal_year, fiscal_month) → dim_fiscal_periods`; cross-schema FK `expense_reports.employee_id → hr.employees`; junctions `invoice_payments`, `vendor_contract_links`; text-heavy `audit_journal`, `vendor_contracts`. |
| `hr` | 16 | Self-referencing `employees.manager_id`; 3 junctions; enum column (`hr.employment_status`); **110-column wide table** `employee_survey_wide`; composite-PK `job_history`; text-heavy `performance_reviews`. |
| `staging` | 16 | **The no-FK zone**: zero declared FKs (cloud-warehouse dump). Obvious name/type/value-overlap joins for inference (`stg_orders.stg_customer_id → stg_customers.id`, etc.), one type-mismatch join (`stg_shipments.stg_order_id` VARCHAR), one orphaned join (`stg_returns.stg_order_id` values 900000+), one realistically named column the engine cannot match (`stg_invoices.customer_id`), and two tables with no PK at all (`stg_inventory`, `stg_exchange_rates`). |
| `analytics` | 46 | Edge cases: reserved-word table `"order"` (columns `"select"`, `"group"`), quoted mixed-case `"CamelCaseEvents"`, 60-char identifiers, `typed_showcase` (uuid / jsonb / numeric[] / text[] / enum / interval / bytea / inet / daterange), 100k-row `events_tall`, zero-row `zero_rows_events`; **25 generated distractor tables** all shaped `(id, name, status, created_at)`; 6 seeded quality-issue tables (below). |

## Seeded quality issues (readiness ground truth)

| # | Issue | Where | Expected |
| - | ----- | ----- | -------- |
| Q1 | empty table | `analytics.quality_empty_orders` (also `analytics.zero_rows_events`) | Critical |
| Q2 | all-null column | `analytics.quality_users.middle_name`, `analytics.quality_sensor_dump.calibration_note` | Critical |
| Q3 | constant column | `analytics.quality_users.country_code` ('IN'), `analytics.quality_sensor_dump.firmware` ('1.0.0') | Info |
| Q4 | high null rate (~70%) | `analytics.quality_users.referral_code` | Warning |
| Q5 | broken FK (inferred) | `analytics.quality_invoices.dim_customer_id` → `sales.dim_customers.id`, 20% orphans | Critical |
| Q6 | broken FK (declared, `NOT VALID`) | `analytics.quality_orders_notvalid.customer_ref` → `sales.dim_customers.id`, 25% orphans | Critical |
| Q7 | mixed-case categorical | `analytics.quality_status_mix.status` ('active'/'Active'/'ACTEVE'…) | **Known gap** — no M2 check; type_mismatch is deferred |
| Q8 | orphaned inferred join | `staging.stg_returns.stg_order_id` (values 900000+) | Critical broken_fk on an inferred relationship |

## Pattern-detection ground truth (declared-FK graph only)

- **Star facts** (≥2 FK targets + ≥2 non-key measure/attribute columns): sales
  `fact_sales`, `fact_returns`, `fact_shipments`, `fact_inventory_snapshots`
  (compact composite-PK fact — its two measures keep it out of the junction
  bucket), `product_reviews`*; finance `fact_invoices`, `fact_payments`,
  `fact_ledger_entries`, `fact_budgets`, `fact_invoice_lines`; hr
  `hr.payroll_items` and other multi-FK tables that satisfy the shape.
  *Text tables that reference two dims legitimately satisfy the detector's
  structural definition.
  **Not** star facts: `hr.employees` (master data — referenced as a dimension
  by many tables and mostly own attributes, excluded by the master-data
  guard); `customer_notes` / `hr.performance_reviews` (only one *distinct*
  FK-target table).
- **Junctions** (≥2 FK targets, ≤1 column that is neither FK-participating
  nor part of the PK): `bridge_product_suppliers`, `bridge_customer_segments`,
  `bridge_promotion_channels`, `invoice_payments`, `vendor_contract_links`,
  `employee_skills`, `employee_benefits`, `employee_training`, `job_history`.
  Compact facts with ≥2 own measure columns (`fact_inventory_snapshots`,
  `staging.stg_inventory`) are **not** junctions.
- **Snowflakes**: every star fact whose dim itself references onward
  (product/store chains in sales). Self-referencing FKs are excluded from the
  pattern graph by design, so snowflakes reachable only through a
  self-reference — `fact_payments`/`fact_ledger_entries` via
  `dim_accounts.parent_account_id` — are **undetectable** (documented
  limitation, see `dla/patterns/base.py`).
- The `staging` schema should contribute **no declared** relationships — only
  inferred ones.

## Files

| File | Contents |
| ---- | -------- |
| `seed/00_schemas.sql` | Schemas + enum types |
| `seed/01_sales.sql` | Star/snowflake region #1 (26 tables) |
| `seed/02_finance.sql` | Star region #2, composite/multi-col keys (21 tables) |
| `seed/03_hr.sql` | Self-ref, junctions, 110-col wide table (16 tables) |
| `seed/04_staging_nofk.sql` | No-FK zone (16 tables) |
| `seed/05_analytics_edge.sql` | Structural edge cases (15 tables) |
| `seed/06_distractors.sql` | 25 generated generic-shape distractors |
| `seed/07_quality_issues.sql` | Seeded quality issues (6 tables) |

Tear down: `docker compose -f apps/dla/tests/fixtures/postgres_large/docker-compose.yaml down -v`
