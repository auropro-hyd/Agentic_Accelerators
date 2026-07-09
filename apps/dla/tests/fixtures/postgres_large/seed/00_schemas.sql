-- Large-scale synthetic fixture (120+ tables across 5 schemas).
-- File 00: schemas + shared enum types. See README.md in this directory for
-- the full map of regions and deliberately seeded issues.

SET client_min_messages = WARNING;

CREATE SCHEMA sales;      -- star + snowflake region #1 (retail)
CREATE SCHEMA finance;    -- star region #2, composite PKs, multi-column FK, self-ref
CREATE SCHEMA hr;         -- self-referencing FK, junctions, 110-column wide table
CREATE SCHEMA staging;    -- NO declared foreign keys (cloud-warehouse dump simulation)
CREATE SCHEMA analytics;  -- structural edge cases, distractors, quality issues

-- Enum types (unusual-type coverage for discovery/profiling)
CREATE TYPE hr.employment_status AS ENUM ('full_time', 'part_time', 'contract', 'terminated');
CREATE TYPE analytics.mood_type  AS ENUM ('happy', 'neutral', 'sad');
CREATE TYPE sales.return_reason  AS ENUM ('damaged', 'wrong_item', 'too_late', 'changed_mind');
