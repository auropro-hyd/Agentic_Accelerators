# Data Layer Accelerator (`dla`)

A command-line tool that turns a data source into a structured,
confidence-tagged **knowledge bundle** on disk — ready for review by
subject-matter experts and consumption by downstream analytical
pipelines.

The source data is never copied, moved, or modified. The tool reads
structure and a small sample of values, and writes a folder of paired
markdown + JSON files describing what it found.

---

## Status

| Component                                                   | Status     |
| ----------------------------------------------------------- | ---------- |
| **Schema discovery, tagging, and bundle writing (M1)**      | Released   |
| **Column profiling and readiness reporting (M2)**           | Released   |
| Auto-drafted descriptions and reviewer edit loop (M3)       | Released   |
| Web review interface for non-technical reviewers (M4)       | Upcoming   |
| Client-documentation import and reconciliation (M5)         | Upcoming   |
| Business glossary and pattern catalog (M6)                  | Upcoming   |
| KPI workbook ingest and coverage analysis (M7)              | Upcoming   |
| Strategy recommender and published bundle schema (M8)       | Upcoming   |

Each milestone is independently demonstrable and **additive** — new
work only writes new directories under `bundle/`; it never modifies
output written by earlier milestones (except through a controlled
provenance state machine that protects reviewer edits from being
overwritten).

---

## Table of contents

- [Why this tool](#why-this-tool)
- [What it produces — the bundle](#what-it-produces--the-bundle)
- [Provenance and idempotency](#provenance-and-idempotency)
- [Prerequisites](#prerequisites)
- [Install](#install)
- [Quickstart with the built-in Postgres fixture](#quickstart-with-the-built-in-postgres-fixture)
- [Quickstart with a CSV folder](#quickstart-with-a-csv-folder)
- [Commands](#commands)
- [Exit codes](#exit-codes)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Development](#development)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why this tool

Creating the knowledge bundle for a new analytical engagement is
typically a multi-week manual analyst task: connect to the warehouse,
catalog tables and columns, identify implicit relationships, profile
for data-quality issues, and write descriptions. This tool automates
the deterministic and the auto-draftable portions, so the human work
shrinks to *reviewing* drafts rather than *authoring* them.

The output is a folder on disk — not a database, not a hosted service.
Reviewers edit files; downstream code reads files. Anything that
should be machine-checked or version-controlled is in plain text and
JSON.

---

## What it produces — the bundle

Every command writes to a single output directory (`./bundle/` by
default). Each artifact is a paired markdown + JSON file:

```text
bundle/
├── bundle.json                              # top-level manifest (counts, schema version)
├── source.md            /  source.json      # the connected source
├── schema/
│   ├── tables/        <schema>.<table>.{md,json}
│   ├── columns/       <schema>.<table>.<col>.{md,json}
│   ├── relationships/ <from>-><to>.{md,json}
│   └── indexes/       <schema>.<table>.<idx>.{md,json}
├── profiles/                                # one pair per column (M2)
│   └── <schema>.<table>.<col>.{md,json}
└── readiness/                               # data-quality report (M2)
    ├── readiness.md                         # human-readable summary, severity-sorted
    └── issues/
        └── readiness_issue.<type>.<seq>.{md,json}
```

Upcoming milestones add more sub-directories (`descriptions/`,
`glossary/`, `patterns/`, `kpi/`, `imports/`, `coverage/`,
`recommendation/`) — each additive.

The **markdown** carries YAML frontmatter for structured metadata plus
a freeform body. The body is the field that reviewers edit. The
**JSON** mirrors the frontmatter for machine consumption.

### Confidence tags on inferred relationships

| Tag        | Meaning                                                                                                       |
| ---------- | ------------------------------------------------------------------------------------------------------------- |
| `Explicit` | The source itself declared the relationship (a database foreign-key constraint).                              |
| `Strong`   | Multiple independent signals agreed (name pattern, type match, value overlap). Reviewer typically accepts.    |
| `Weak`     | One signal only. Reviewer should look at it before relying on it.                                             |

The `signals` array on every relationship records which evidence
contributed (`declared_fk`, `name_match`, `type_match`,
`value_overlap`), so the tag is always auditable.

### Readiness issue severities (M2)

| Severity   | Examples                                                                                |
| ---------- | --------------------------------------------------------------------------------------- |
| `Critical` | Broken foreign key, empty table, all-null column.                                       |
| `Warning`  | Column with high null rate (≥ 50%), type mismatch (planned).                            |
| `Info`     | Constant-value column (tiny samples), unprofiled column (permission denied, etc.).      |

Each issue carries a structured `details` block and a plain-language
`suggestion` for remediation.

---

## Provenance and idempotency

Every artifact carries a `provenance` field declaring how it came to
exist:

| Value                          | Meaning                                                                                  |
| ------------------------------ | ---------------------------------------------------------------------------------------- |
| `discovered`                   | Came from the connector (database introspection or CSV parsing).                          |
| `client-provided`              | Loaded from a client-supplied dictionary (Upcoming).                                      |
| `client-provided-reconciled`   | Reconciled against discovered evidence (Upcoming).                                        |
| `sme-authored`                 | Authored by a subject-matter reviewer.                                                    |

Additional provenance values for auto-generated drafts and their
post-edit states are introduced by upcoming milestones; the same state
machine governs all of them.

A state machine controls which provenance can overwrite which. The
bundle writer enforces it — **reviewer edits are never silently
lost**, even when a re-run pulls in upstream schema changes.

Running any `dla` command twice in a row against an unchanged source
produces **zero file diffs** — not even modification times move. This
is the substrate that makes safe, repeatable re-runs possible.

---

## Prerequisites

- Python 3.11 or newer
- [`uv`](https://github.com/astral-sh/uv) (Python project / package
  manager). Install on macOS:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker (only required for the included Postgres fixture; not for
  pointing the tool at your own database)

The tool itself depends on SQLAlchemy + psycopg2 (Postgres),
pandas (CSV), Typer (CLI), Pydantic (config), and structlog
(structured logging). Everything resolves through `uv sync`.

---

## Install

```bash
git clone https://github.com/auropro-hyd/Agentic_Accelerators.git
cd Agentic_Accelerators
bash scripts/install.sh
```

The install script runs `uv sync` and registers the package for
editable use so `uv run dla` finds the source under `src/dla/`.

Verify:

```bash
uv run dla --help
uv run dla version    # prints: 0.1.0
```

---

## Quickstart with the built-in Postgres fixture

The repository ships with a 15-table synthetic retail Postgres fixture
suitable for end-to-end testing. It includes deliberately seeded
data-quality issues (a broken foreign key, an empty table, all-null
columns, a high-null-rate column, constant-value columns) so the
readiness report has interesting output.

```bash
# 1. Start the fixture
docker compose -f tests/fixtures/postgres/docker-compose.yaml up -d
docker exec dla_fixture_postgres pg_isready -U dla -d dla_fixture

# 2. Export the fixture password (any password works for your own DB —
#    the YAML names the env var to read it from, not the value).
export DLA_DB_PASSWORD=dla_dev_password

# 3. Discover schema (M1)
uv run dla discover --config config/examples/postgres_minimal.yaml

# 4. Profile every column (M2)
uv run dla profile --config config/examples/postgres_minimal.yaml

# 5. Generate the readiness report (M2)
uv run dla readiness --config config/examples/postgres_minimal.yaml

# 6. Inspect the bundle
ls bundle/
cat bundle/readiness/readiness.md
cat bundle/schema/columns/public.orders.status.md

# 7. Tear down when done
docker compose -f tests/fixtures/postgres/docker-compose.yaml down -v
```

After step 5, expect roughly:

```text
Readiness report complete.
  source_id:    fixture_postgres
  total issues: 47
    critical  7
    warning   1
    info      39
```

---

## Quickstart with a CSV folder

Many engagements start with a folder of CSV files (a warehouse export)
rather than a live database connection.

```bash
uv run dla discover --config config/examples/csv_folder.yaml
ls bundle_csv/schema/
cat bundle_csv/schema/relationships/orders.customer_id->customers.id.md
```

Because CSV files cannot declare foreign keys, all relationships in a
CSV bundle are **inferred** — and tagged `Strong` or `Weak`
accordingly, with the supporting signals listed on each artifact.

---

## Commands

All commands take a YAML configuration via `--config <path>`. The
configured `runtime.bundle_dir` (or the `--bundle-dir` override)
controls where output lands.

| Command                                                                | Purpose                                                                                                            |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `dla --help`                                                           | Top-level help; lists all subcommands.                                                                             |
| `dla version`                                                          | Print the version string.                                                                                          |
| `dla discover --config <yaml>`                                         | Connect to the configured source, discover schema, write `bundle/source.*`, `bundle/schema/*`, and the manifest. |
| `dla discover --config <yaml> --bundle-dir <path>`                     | Override the output location for this run.                                                                         |
| `dla discover --config <yaml> --dry-run`                               | Plan only — print the counts of what would be written; do not touch disk.                                          |
| `dla profile --config <yaml>`                                          | For every column already in the bundle, sample, compute stats, and write a profile artifact.                       |
| `dla profile --config <yaml> --mode full_scan`                         | Profile by reading every row (exact stats; slower than the default sampling mode).                                 |
| `dla profile --config <yaml> --table <schema.table>`                   | Restrict profiling to one table — useful after a schema change.                                                    |
| `dla readiness --config <yaml>`                                        | Walk the bundle, detect data-quality issues, write `bundle/readiness/issues/*` and `bundle/readiness/readiness.md`. |
| `dla readiness --config <yaml> --severity {critical,warning,info,all}` | Restrict terminal output to a severity (the full report is still written to disk).                                 |

Help for any subcommand:

```bash
uv run dla discover --help
uv run dla profile --help
uv run dla readiness --help
```

---

## Exit codes

CI gates and scripts can branch on the kind of failure.

| Code | Meaning                                                                            |
| ---- | ---------------------------------------------------------------------------------- |
| 0    | Success.                                                                           |
| 1    | Generic failure (unhandled exception). Check stderr for the message.               |
| 2    | Connection error — bad credentials, unreachable host, missing CSV folder, etc.     |
| 3    | Configuration error — missing or malformed YAML, invalid fields, missing env var. |

(Codes 4, 5, 6 are reserved for upcoming milestones.)

---

## Configuration

A configuration YAML defines the data source, the bundle output
location, and the thresholds that control discovery and readiness
checks.

### Postgres example

```yaml
source:
  source_id: my_warehouse
  display_name: My Warehouse (production)
  provider: postgres
  postgres:
    host: warehouse.example.com
    port: 5432
    database: analytics
    username: dla_reader
    password_env_var: MY_DB_PASSWORD     # value is read from this env var; never stored in YAML
    schemas:
      - public
      - reporting

runtime:
  bundle_dir: ./bundle
  log_format: console        # or: json

thresholds:
  name_match_min_score: 0.85               # minimum string similarity for relationship-name inference
  value_overlap_min_ratio: 0.5             # minimum sampled-value overlap to call an inferred FK "Strong"
  high_null_rate: 0.5                      # ≥ 50% nulls → Warning
  high_null_rate_critical: 0.9             # ≥ 90% nulls → Critical
  sample_budget_rows: 10000                # default per-column sample size for profiling
  constant_column_severity_info: true      # constant-value columns land at Info (set false for Warning)
```

### CSV-folder example

```yaml
source:
  source_id: my_csv_export
  display_name: Quarterly CSV export
  provider: csv_folder
  csv_folder:
    folder: ./data/exports
    glob: "*.csv"
    encoding: utf-8

runtime:
  bundle_dir: ./bundle_csv
  log_format: console
```

Two ready-to-run examples ship in the repo:

- `config/examples/postgres_minimal.yaml` — points at the included Postgres fixture.
- `config/examples/csv_folder.yaml` — points at the included CSV fixture.

Defaults for every threshold live in `config/default.yaml`; the
per-engagement YAML only needs to override what differs.

### Secrets

Passwords and tokens are **never** stored in YAML. The config names
the environment variable to read them from
(`postgres.password_env_var`), and the loader fails fast with exit
code 3 if the env var is unset.

---

## Project structure

```text
.
├── config/                       # default + example YAML configs
│   ├── default.yaml
│   └── examples/
├── docs/                         # public-facing design + scope docs
├── scripts/install.sh            # one-shot dev environment setup
├── src/dla/                      # all source code
│   ├── bundle/                   # on-disk format: schema, layout, provenance, reader, writer
│   ├── cli/                      # Typer CLI entrypoints
│   ├── config/                   # pydantic config models + loader
│   ├── connectors/               # Postgres, CSV (extensible to other providers)
│   ├── discovery/                # schema introspection, relationship inference, confidence tagging
│   ├── profiling/                # samplers, statistics, profile engine
│   ├── readiness/                # data-quality checks, severity, report assembly
│   └── logging_ctx/              # structured logging configuration + context manager
└── tests/
    ├── fixtures/
    │   ├── postgres/             # docker-compose + seed SQL (clean + quality-issues seeds)
    │   └── csv/                  # synthetic CSV files
    └── unit/                     # unit test suite
```

---

## Development

### One-time setup

```bash
bash scripts/install.sh
```

This wraps:

```bash
uv sync
# plus a macOS-only fix-up of the editable-install .pth file
```

### Adding a new connector

The discovery and profiling engines are provider-agnostic. To add a
new source (Snowflake, BigQuery, S3, etc.):

1. Implement the `SourceConnector` protocol in
   `src/dla/connectors/base.py` — `connect()`, `introspect_schema()`,
   `sample_column()`, `close()`.
2. Add a corresponding `*ConnectionConfig` model in
   `src/dla/config/models.py` and register the provider literal on
   `SourceConfig.provider`.
3. Add a `build(cfg)` factory and register it in the CLI's
   connector dispatch (`src/dla/cli/discover.py`).

A future Snowflake connector is on the [Roadmap](#roadmap).

---

## Testing

### Unit tests

```bash
uv run pytest tests/unit -q
```

Current count: **67 unit tests** (M1 substrate, provenance state
machine, bundle writer, profiling statistics, readiness checks,
configuration loader).

### Linting and formatting

```bash
uv run ruff check .
```

### Proving idempotency end-to-end

```bash
find bundle -type f -exec stat -f "%m %N" {} \; | sort > /tmp/before.txt
uv run dla discover  --config config/examples/postgres_minimal.yaml
uv run dla profile   --config config/examples/postgres_minimal.yaml
uv run dla readiness --config config/examples/postgres_minimal.yaml
find bundle -type f -exec stat -f "%m %N" {} \; | sort > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt && echo "IDEMPOTENT"
```

---

## Troubleshooting

| Symptom                                                  | Likely cause                                                        | Fix                                                                                                                              |
| -------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `ModuleNotFoundError: No module named 'dla'`             | Editable-install `.pth` file not registered                         | Re-run `bash scripts/install.sh`                                                                                                |
| `connection error: ... password authentication failed`   | `*_password_env_var` is unset, or value is wrong                    | `export DLA_DB_PASSWORD=...` (or the variable named in your YAML)                                                                |
| Exit code 3, no obvious message                          | Bad / missing config path, malformed YAML, or invalid field         | Check stderr for the validation error string                                                                                     |
| Postgres fixture container will not start                | Port 55432 already in use on the host                               | `lsof -i :55432` to find the conflicting process, or change the host port in `tests/fixtures/postgres/docker-compose.yaml`     |
| `uv sync` hangs                                          | Network                                                             | `UV_HTTP_TIMEOUT=120 uv sync` and/or retry                                                                                       |
| Bundle re-run produces diffs                             | Source genuinely changed, or someone hand-edited a bundle file      | Verify nothing in `bundle/` was edited externally; check that the source has not changed                                         |
| `dla profile` reports many columns as `unprofiled`       | The connection user lacks SELECT on those tables, or types unsupported | Grant the discovery role `SELECT` on each table; check `bundle/profiles/*.json` for `error_reason`                              |
| Readiness counts differ by ±1 between two runs           | Sampling-order dependence for tiny tables                           | Acceptable for fixtures. Headline counts (Critical / Warning / Info totals) are stable; minor numeric details may drift by one. |

---

## Roadmap

Each milestone is delivered as an independently demonstrable
increment, additive to the bundle.

| Milestone | Theme                                                                                                | Status     |
| --------- | ---------------------------------------------------------------------------------------------------- | ---------- |
| **M1**    | Connect, discover, tag, bundle (Postgres + CSV)                                                      | Released   |
| **M2**    | Column profiling + readiness report (Critical / Warning / Info)                                      | Released   |
| **M3**    | Auto-drafted descriptions grounded in discovered facts and profiles; markdown review loop with edit preservation | Upcoming   |
| **M4**    | Local web interface for reviewing and editing drafts                                                  | Upcoming   |
| **M5**    | Client-documentation import (CSV / Excel / dbt manifest) with reconciliation against discovered evidence | Upcoming   |
| **M6**    | Cross-engagement glossary and pattern catalog (audit, junction, lookup, etc.)                         | Upcoming   |
| **M7**    | KPI workbook ingest and coverage analysis                                                             | Upcoming   |
| **M8**    | Strategy recommender, published bundle JSON schema, and a Snowflake connector                         | Upcoming   |

For the published scope document see
[`docs/Accelerators_Scope_v5.md`](docs/Accelerators_Scope_v5.md).

### Connector roadmap

| Source     | Status     |
| ---------- | ---------- |
| Postgres   | Released   |
| CSV folder | Released   |
| Snowflake  | Upcoming   |

---

## Contributing

1. Cut a `feat/<short-description>` branch from `main`.
2. Make changes; add or update unit tests under `tests/unit/`.
3. Confirm `uv run pytest tests/unit -q` and `uv run ruff check .` are both clean.
4. Run the idempotency check in the [Testing](#testing) section.
5. Open a pull request against `main` describing the change and the
   acceptance evidence.

Bundles are part of the public contract. Changes to bundle layout,
artifact shape, or the provenance state machine require a corresponding
update to the relevant document under `docs/` and to the published
schema (once shipped in M8).

---

## License

License to be determined. Until then, all rights reserved. Internal
use only.
