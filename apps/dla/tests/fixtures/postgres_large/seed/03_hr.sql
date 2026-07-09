-- File 03: hr schema (16 tables).
-- Ground truth:
--   * Self-referencing FK: employees.manager_id -> employees.id.
--   * Junctions: employee_skills, employee_benefits, employee_training.
--   * Composite PK: job_history (employee_id, started_on).
--   * Wide table: employee_survey_wide has 110 columns (q001..q100 + 10 base
--     columns) — generated via a DO block for maintainability.
--   * Enum column: employees.status uses hr.employment_status.
--   * Text-heavy: performance_reviews.summary_text.
--   * Cross-schema declared FK (added at the end): finance.expense_reports.employee_id
--     -> hr.employees(id).

SET client_min_messages = WARNING;
SET search_path = hr;

CREATE TABLE locations (
    id       SERIAL PRIMARY KEY,
    city     VARCHAR(80) NOT NULL,
    country  CHAR(2) NOT NULL,
    timezone VARCHAR(40)
);

CREATE TABLE departments (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(80) NOT NULL UNIQUE,
    budget  NUMERIC(14,2)
);

CREATE TABLE positions (
    id      SERIAL PRIMARY KEY,
    title   VARCHAR(120) NOT NULL,
    level   SMALLINT NOT NULL,
    band    VARCHAR(8)
);

CREATE TABLE employees (
    id            SERIAL PRIMARY KEY,
    employee_code VARCHAR(16) NOT NULL UNIQUE,
    full_name     VARCHAR(160) NOT NULL,
    email         VARCHAR(255) NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    position_id   INTEGER NOT NULL REFERENCES positions(id),
    location_id   INTEGER REFERENCES locations(id),
    manager_id    INTEGER REFERENCES employees(id),         -- self-referencing FK
    status        hr.employment_status NOT NULL DEFAULT 'full_time',
    hired_on      DATE NOT NULL,
    salary        NUMERIC(12,2),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_employees_manager ON employees(manager_id);

CREATE TABLE skills (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(80) NOT NULL UNIQUE
);

CREATE TABLE employee_skills (
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    skill_id     INTEGER NOT NULL REFERENCES skills(id),
    proficiency  SMALLINT,
    PRIMARY KEY (employee_id, skill_id)
);

CREATE TABLE benefits (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    annual_cost NUMERIC(10,2)
);

CREATE TABLE employee_benefits (
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    benefit_id   INTEGER NOT NULL REFERENCES benefits(id),
    enrolled_on  DATE,
    PRIMARY KEY (employee_id, benefit_id)
);

CREATE TABLE training_courses (
    id       SERIAL PRIMARY KEY,
    title    VARCHAR(160) NOT NULL,
    hours    SMALLINT
);

CREATE TABLE employee_training (
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    course_id    INTEGER NOT NULL REFERENCES training_courses(id),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (employee_id, course_id)
);

CREATE TABLE payroll_runs (
    id        SERIAL PRIMARY KEY,
    run_date  DATE NOT NULL,
    period    VARCHAR(16) NOT NULL,
    status    VARCHAR(16) NOT NULL
);

CREATE TABLE payroll_items (
    id           SERIAL PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES payroll_runs(id),
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    gross        NUMERIC(12,2) NOT NULL,
    net          NUMERIC(12,2) NOT NULL,
    deductions   NUMERIC(12,2) NOT NULL DEFAULT 0
);

CREATE TABLE performance_reviews (
    id           SERIAL PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    reviewer_id  INTEGER REFERENCES employees(id),
    period       VARCHAR(16) NOT NULL,
    rating       SMALLINT,
    summary_text TEXT NOT NULL
);

CREATE TABLE job_history (
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    started_on   DATE NOT NULL,
    position_id  INTEGER NOT NULL REFERENCES positions(id),
    ended_on     DATE,
    PRIMARY KEY (employee_id, started_on)                  -- composite PK
);

CREATE TABLE emergency_contacts (
    id           SERIAL PRIMARY KEY,
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    name         VARCHAR(160) NOT NULL,
    relationship VARCHAR(40),
    phone        VARCHAR(32)
);

-- Wide table: 10 base columns + q001..q100 -> 110 columns total.
DO $$
DECLARE
    cols text := '';
BEGIN
    FOR i IN 1..100 LOOP
        cols := cols || format(', q%s SMALLINT', lpad(i::text, 3, '0'));
    END LOOP;
    EXECUTE 'CREATE TABLE hr.employee_survey_wide ('
         || 'id SERIAL PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES hr.employees(id), '
         || 'survey_year SMALLINT NOT NULL, submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(), '
         || 'is_anonymous BOOLEAN NOT NULL DEFAULT FALSE, engagement_score NUMERIC(5,2), '
         || 'nps SMALLINT, tenure_bucket VARCHAR(16), comments TEXT, locale VARCHAR(8)'
         || cols || ')';
END $$;

-- ============ seed data ============

INSERT INTO locations (city, country, timezone) VALUES
    ('London', 'GB', 'Europe/London'), ('Berlin', 'DE', 'Europe/Berlin'),
    ('Austin', 'US', 'America/Chicago'), ('Hyderabad', 'IN', 'Asia/Kolkata');

INSERT INTO departments (name, budget)
SELECT 'Department ' || i, 1000000 + i * 50000 FROM generate_series(1, 8) i;

INSERT INTO positions (title, level, band)
SELECT 'Position ' || i, 1 + (i % 6), 'B' || (1 + i % 6) FROM generate_series(1, 20) i;

INSERT INTO employees (employee_code, full_name, email, department_id, position_id,
                       location_id, manager_id, status, hired_on, salary)
SELECT 'EMP-' || lpad(i::text, 4, '0'), 'Employee ' || i, 'emp' || i || '@example.com',
       1 + (i % 8), 1 + (i % 20), 1 + (i % 4),
       CASE WHEN i <= 8 THEN NULL ELSE 1 + (i % 8) END,   -- first 8 are top-level managers
       (ARRAY['full_time','part_time','contract','terminated'])[1 + i % 4]::hr.employment_status,
       DATE '2019-01-01' + i * 9, 40000 + i * 350
FROM generate_series(1, 120) i;

INSERT INTO skills (name) SELECT 'Skill ' || i FROM generate_series(1, 25) i;

INSERT INTO employee_skills (employee_id, skill_id, proficiency)
SELECT 1 + (i % 120), 1 + (i % 25), 1 + (i % 5) FROM generate_series(1, 300) i
ON CONFLICT DO NOTHING;

INSERT INTO benefits (name, annual_cost)
SELECT 'Benefit ' || i, 500 + i * 120 FROM generate_series(1, 10) i;

INSERT INTO employee_benefits (employee_id, benefit_id, enrolled_on)
SELECT 1 + (i % 120), 1 + (i % 10), DATE '2024-01-01' + i FROM generate_series(1, 240) i
ON CONFLICT DO NOTHING;

INSERT INTO training_courses (title, hours)
SELECT 'Course ' || i, 2 + (i % 40) FROM generate_series(1, 18) i;

INSERT INTO employee_training (employee_id, course_id, completed_at)
SELECT 1 + (i % 120), 1 + (i % 18), now() - (i || ' days')::interval
FROM generate_series(1, 260) i
ON CONFLICT DO NOTHING;

INSERT INTO payroll_runs (run_date, period, status)
SELECT DATE '2025-01-31' + i * 30, '2025-M' || lpad((1 + i % 12)::text, 2, '0'),
       CASE WHEN i < 14 THEN 'posted' ELSE 'draft' END
FROM generate_series(0, 17) i;

INSERT INTO payroll_items (run_id, employee_id, gross, net, deductions)
SELECT 1 + (i % 18), 1 + (i % 120), round((3000 + i % 4000)::numeric, 2),
       round(((3000 + i % 4000) * 0.72)::numeric, 2), round(((3000 + i % 4000) * 0.28)::numeric, 2)
FROM generate_series(1, 1500) i;

INSERT INTO performance_reviews (employee_id, reviewer_id, period, rating, summary_text)
SELECT 1 + (i % 120), 1 + (i % 8), '2025-H' || (1 + i % 2), 1 + (i % 5),
       'Consistently delivered against the quarterly objectives and took ownership of the '
       || 'incident review process without being asked. Communication with partner teams has '
       || 'improved markedly since the last cycle, though estimation on larger projects still '
       || 'trends optimistic. Recommend pairing with a senior mentor next half and revisiting '
       || 'the promotion conversation once the reliability workstream lands. Review ' || i
FROM generate_series(1, 180) i;

INSERT INTO job_history (employee_id, started_on, position_id, ended_on)
SELECT 1 + (i % 120), DATE '2019-01-01' + i * 13, 1 + (i % 20),
       CASE WHEN i % 3 = 0 THEN DATE '2021-01-01' + i * 13 END
FROM generate_series(1, 200) i
ON CONFLICT DO NOTHING;

INSERT INTO emergency_contacts (employee_id, name, relationship, phone)
SELECT 1 + (i % 120), 'Contact ' || i, (ARRAY['spouse','parent','sibling','friend'])[1 + i % 4],
       '+1-555-' || lpad(i::text, 4, '0')
FROM generate_series(1, 150) i;

INSERT INTO hr.employee_survey_wide (employee_id, survey_year, engagement_score, nps, tenure_bucket, comments, locale,
    q001, q002, q003, q004, q005)
SELECT 1 + (i % 120), 2025 + (i % 2), round((1 + random() * 4)::numeric, 2), (i % 21) - 10,
       (ARRAY['<1y','1-3y','3-5y','5y+'])[1 + i % 4],
       'Mostly satisfied with the tooling budget but the onboarding wiki is badly out of date.',
       'en-US', 1 + (i % 5), 1 + (i % 5), 1 + (i % 5), 1 + (i % 5), 1 + (i % 5)
FROM generate_series(1, 80) i;

-- Fill the remaining q006..q100 with values for realism.
DO $$
DECLARE
    stmt text := '';
BEGIN
    FOR i IN 6..100 LOOP
        stmt := stmt || format('q%s = 1 + (id %% 5), ', lpad(i::text, 3, '0'));
    END LOOP;
    stmt := left(stmt, length(stmt) - 2);
    EXECUTE 'UPDATE hr.employee_survey_wide SET ' || stmt;
END $$;

-- Cross-schema declared FK (finance -> hr).
ALTER TABLE finance.expense_reports
    ADD CONSTRAINT fk_expense_reports_employee
    FOREIGN KEY (employee_id) REFERENCES hr.employees(id);
