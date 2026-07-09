-- File 05: analytics schema — structural edge cases (15 tables).
-- Ground truth:
--   * Reserved-word identifiers: table "order" with columns "select" and "group".
--   * Mixed-case quoted identifiers: "CamelCaseEvents" with "eventId", "eventName".
--   * Long identifiers (60 chars, near the 63-char Postgres limit):
--     tbl_customer_lifetime_value_rolling_window_aggregation_v2025
--     with column cumulative_gross_merchandise_value_net_of_returns_and_promos.
--   * Unusual types: typed_showcase (uuid PK, jsonb, numeric[], text[], enum,
--     timestamptz, time, interval, bytea, inet, daterange).
--   * Tall table: events_tall with 100,000 rows (sampling behavior).
--   * Zero-row table with a full schema: zero_rows_events.

SET client_min_messages = WARNING;
SET search_path = analytics;

-- Reserved-word table + columns (all quoted)
CREATE TABLE "order" (
    id          SERIAL PRIMARY KEY,
    "select"    VARCHAR(40),
    "group"     VARCHAR(40),
    status      VARCHAR(24),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Mixed-case quoted identifiers
CREATE TABLE "CamelCaseEvents" (
    "eventId"    SERIAL PRIMARY KEY,
    "eventName"  VARCHAR(80) NOT NULL,
    "occurredAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "payloadJson" JSONB
);

-- 60-character identifiers (Postgres limit is 63)
CREATE TABLE tbl_customer_lifetime_value_rolling_window_aggregation_v2025 (
    id SERIAL PRIMARY KEY,
    cumulative_gross_merchandise_value_net_of_returns_and_promos NUMERIC(16,2),
    as_of DATE
);

-- Unusual-type showcase
CREATE TABLE typed_showcase (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload      JSONB,
    price_points NUMERIC(12,4)[],
    tags         TEXT[],
    mood         analytics.mood_type,
    seen_at      TIMESTAMPTZ,
    daily_at     TIME,
    lifetime     INTERVAL,
    blob         BYTEA,
    client_ip    INET,
    active_range DATERANGE
);

-- Tall table: ~100k rows for sampling behavior
CREATE TABLE events_tall (
    id          BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    event_type  VARCHAR(40) NOT NULL,
    user_ref    INTEGER,
    duration_ms INTEGER,
    payload     JSONB
);

-- Zero rows, full schema
CREATE TABLE zero_rows_events (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(80) NOT NULL,
    status      VARCHAR(24),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Rollup / product-analytics tables (generic column names on purpose)
CREATE TABLE daily_kpi_rollup (
    id          SERIAL PRIMARY KEY,
    day         DATE NOT NULL,
    name        VARCHAR(80) NOT NULL,
    value       NUMERIC(16,4),
    status      VARCHAR(24),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE monthly_kpi_rollup (
    id          SERIAL PRIMARY KEY,
    month       DATE NOT NULL,
    name        VARCHAR(80) NOT NULL,
    value       NUMERIC(16,4),
    status      VARCHAR(24),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE funnel_steps (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(80) NOT NULL,
    step_order  SMALLINT NOT NULL,
    status      VARCHAR(24),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cohort_retention (
    id           SERIAL PRIMARY KEY,
    cohort_month DATE NOT NULL,
    period_no    SMALLINT NOT NULL,
    retained_pct NUMERIC(6,3),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ab_test_results (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    variant     VARCHAR(24) NOT NULL,
    metric      NUMERIC(12,6),
    status      VARCHAR(24),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE page_views (
    id          BIGSERIAL PRIMARY KEY,
    url         VARCHAR(240) NOT NULL,
    viewed_at   TIMESTAMPTZ NOT NULL,
    user_ref    INTEGER,
    status      VARCHAR(24)
);

CREATE TABLE sessions (
    id          BIGSERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    device      VARCHAR(40),
    status      VARCHAR(24)
);

CREATE TABLE search_queries (
    id          BIGSERIAL PRIMARY KEY,
    query_text  TEXT NOT NULL,
    results     INTEGER,
    searched_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE feature_flags (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(80) NOT NULL UNIQUE,
    enabled     BOOLEAN NOT NULL DEFAULT FALSE,
    status      VARCHAR(24),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ seed data ============

INSERT INTO "order" ("select", "group", status)
SELECT 'choice ' || i, 'bucket ' || (i % 5), (ARRAY['open','closed'])[1 + i % 2]
FROM generate_series(1, 40) i;

INSERT INTO "CamelCaseEvents" ("eventName", "payloadJson")
SELECT 'Event' || i, jsonb_build_object('seq', i, 'ok', i % 2 = 0)
FROM generate_series(1, 60) i;

INSERT INTO tbl_customer_lifetime_value_rolling_window_aggregation_v2025
    (cumulative_gross_merchandise_value_net_of_returns_and_promos, as_of)
SELECT round((1000 + i * 37.5)::numeric, 2), DATE '2025-01-01' + i
FROM generate_series(1, 90) i;

INSERT INTO typed_showcase (payload, price_points, tags, mood, seen_at, daily_at, lifetime, blob, client_ip, active_range)
SELECT jsonb_build_object('k', i, 'nested', jsonb_build_object('deep', i * 2)),
       ARRAY[round((i * 1.1)::numeric, 4), round((i * 2.2)::numeric, 4)],
       ARRAY['tag' || i, 'tag' || (i + 1)],
       (ARRAY['happy','neutral','sad'])[1 + i % 3]::analytics.mood_type,
       now() - (i || ' hours')::interval,
       make_time(i % 24, i % 60, 0),
       (i || ' days')::interval,
       decode(md5(i::text), 'hex'),
       ('10.0.' || (i % 255) || '.' || (1 + i % 254))::inet,
       daterange(DATE '2026-01-01', DATE '2026-01-01' + i)
FROM generate_series(1, 50) i;

INSERT INTO events_tall (occurred_at, event_type, user_ref, duration_ms, payload)
SELECT now() - (i || ' seconds')::interval,
       (ARRAY['click','view','scroll','hover','submit'])[1 + i % 5],
       1 + (i % 5000), (i * 13) % 30000,
       jsonb_build_object('n', i % 100)
FROM generate_series(1, 100000) i;

INSERT INTO daily_kpi_rollup (day, name, value, status)
SELECT DATE '2026-01-01' + (i % 180), (ARRAY['revenue','orders','aov','traffic'])[1 + i % 4],
       round((100 + i * 1.7)::numeric, 4), 'final'
FROM generate_series(1, 720) i;

INSERT INTO monthly_kpi_rollup (month, name, value, status)
SELECT date_trunc('month', DATE '2025-01-01' + (i % 18) * 31)::date,
       (ARRAY['revenue','orders','aov','traffic'])[1 + i % 4],
       round((3000 + i * 21)::numeric, 4), 'final'
FROM generate_series(1, 72) i;

INSERT INTO funnel_steps (name, step_order, status)
SELECT 'Step ' || i, i, 'live' FROM generate_series(1, 8) i;

INSERT INTO cohort_retention (cohort_month, period_no, retained_pct)
SELECT date_trunc('month', DATE '2025-01-01' + m * 31)::date, p, round((90 - p * 6.5)::numeric, 3)
FROM generate_series(0, 11) m, generate_series(0, 8) p;

INSERT INTO ab_test_results (name, variant, metric, status)
SELECT 'Experiment ' || (1 + i / 2), (ARRAY['control','treatment'])[1 + i % 2],
       round((0.01 + i * 0.001)::numeric, 6), (ARRAY['running','done'])[1 + i % 2]
FROM generate_series(1, 60) i;

INSERT INTO page_views (url, viewed_at, user_ref, status)
SELECT 'https://shop.example.com/' || (i % 200), now() - (i || ' minutes')::interval,
       1 + (i % 2000), 'ok'
FROM generate_series(1, 5000) i;

INSERT INTO sessions (started_at, ended_at, device, status)
SELECT now() - (i || ' hours')::interval, now() - (i || ' hours')::interval + interval '25 minutes',
       (ARRAY['ios','android','web'])[1 + i % 3], (ARRAY['closed','abandoned'])[1 + i % 2]
FROM generate_series(1, 1200) i;

INSERT INTO search_queries (query_text, results, searched_at)
SELECT 'where can I find ' || (ARRAY['red shoes','wireless earbuds','linen napkins','gift cards'])[1 + i % 4]
       || ' with next day delivery in size ' || (i % 12),
       i % 40, now() - (i || ' minutes')::interval
FROM generate_series(1, 900) i;

INSERT INTO feature_flags (name, enabled, status)
SELECT 'flag_' || i, i % 2 = 0, 'live' FROM generate_series(1, 30) i;
