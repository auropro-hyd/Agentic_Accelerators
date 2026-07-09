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
| **Auto-drafted descriptions and reviewer edit loop (M3)**   | Released   |
| **Web review interface for non-technical reviewers (M4)**   | Released   |
| **Client-documentation import and reconciliation (M5)**     | Released   |
| **Business glossary and pattern catalog (M6)**              | Released   |
| **KPI workbook, coverage, prior-bundle import, term mapping (M7)** | Released   |
| **Strategy recommender, bundle contract, end-to-end orchestrator (M8)** | Released   |

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
- [Auto-drafted descriptions (M3)](#auto-drafted-descriptions-m3)
- [Web review interface (M4)](#web-review-interface-m4)
- [Client-documentation import and reconciliation (M5)](#client-documentation-import-and-reconciliation-m5)
- [Business glossary and pattern catalog (M6)](#business-glossary-and-pattern-catalog-m6)
- [KPI workbook and review coverage (M7)](#kpi-workbook-and-review-coverage-m7)
- [Full pipeline and strategy recommendation (M8)](#full-pipeline-and-strategy-recommendation-m8)
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
├── readiness/                               # data-quality report (M2)
│   ├── readiness.md                         # human-readable summary, severity-sorted
│   └── issues/
│       └── readiness_issue.<type>.<seq>.{md,json}
├── descriptions/                            # auto-drafted + reviewed text (M3/M4)
│   ├── table.<schema>.<table>.{md,json}
│   └── column.<schema>.<table>.<col>.{md,json}
├── glossary/                                # recurring business terms (M6)
├── patterns/                                # detected star/snowflake/junction/audit shapes (M6)
├── kpi/                                     # SME-authored KPI workbook entries (M7)
├── hierarchies/                             # SME-authored dimension drill-down hierarchies
├── coverage/                                # SME review coverage per artifact type (M7)
├── term_mappings/                           # SME term-mapping rules (M7)
├── imports/                                 # client-doc import + reconciliation (M5)
│   ├── artifacts/        <format>.<target>.{md,json}     # imported records
│   └── reconciliation/   <result-key>.{md,json}          # match / conflict / gap buckets
├── recommendation/                          # the strategy recommendation, one per run (M8)
└── .run_state.json                          # orchestrator step state, resume support (M8)
```

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
| `Warning`  | Column with high null rate (≥ 50%), relationship whose endpoint column types mismatch (`type_mismatch`). |
| `Info`     | Constant-value column (tiny samples), unprofiled or errored column (permission denied, profiling failure, etc.). |

Each issue carries a structured `details` block and a plain-language
`suggestion` for remediation.

---

## Provenance and idempotency

Every artifact carries a `provenance` field declaring how it came to
exist:

| Value                          | Meaning                                                                                  |
| ------------------------------ | ---------------------------------------------------------------------------------------- |
| `discovered`                   | Came from the connector (database introspection or CSV parsing).                          |
| `ai-drafted`                   | Auto-drafted from discovered facts + profile evidence (M3).                               |
| `ai-drafted-edited`            | An auto-draft a reviewer edited or accepted (M3/M4).                                       |
| `client-provided`              | Loaded from a client-supplied dictionary, notes, or dbt manifest (M5).                    |
| `client-provided-reconciled`   | A client-provided import a reviewer reconciled against discovered evidence (M5).          |
| `sme-authored`                 | Authored or settled by a subject-matter reviewer.                                         |

A state machine controls which provenance can overwrite which. The
bundle writer enforces it — **reviewer edits are never silently
lost**, even when a re-run pulls in upstream schema changes.

Running any `dla` command twice in a row against an unchanged source
produces **zero file diffs** — not even modification times move. This
is the substrate that makes safe, repeatable re-runs possible.

---

## Where the bundle goes (downstream)

`dla` is **Layer 1** of an 8-layer accelerator stack. Its output — the `bundle/`
directory, the `recommendation/` artifact, and the published
`config/schemas/bundle-schema.json` — is the hand-off to **Layer 2, the Knowledge
Representation Assembler**, which uses the recommended strategy to build what the
agents query:

- `recommend` → `plain_schema` → straight relational modeling
- `recommend` → `vector` → a vector/semantic store over the free-text fields
- `recommend` → `knowledge_graph` → a graph over the bundle's entities + relationships

Everything is JSON, self-describing via `artifact_type`, and provenance-tagged so
a downstream consumer can tell discovered fact from AI draft from human-authored
truth. The machine-readable contract is `docs/bundle-contract.md`.

---

## Prerequisites

- Python 3.11 or newer
- [`uv`](https://github.com/astral-sh/uv) (Python project / package
  manager). Install on macOS:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker (only required for the included Postgres fixture; not for
  pointing the tool at your own database)

The tool depends on SQLAlchemy + psycopg2 (Postgres), pandas + openpyxl
(CSV / Excel), Typer (CLI), Pydantic (config), structlog (structured
logging), a provider-agnostic LLM gateway for auto-drafting (M3),
FastAPI + Jinja2 + HTMX for the local web interface (M4), and rapidfuzz
for reconciliation matching (M5). Everything resolves through `uv sync`.

The web interface and the LLM gateway run locally; no data leaves the
machine unless you explicitly configure a hosted model provider.

---

## Install

```bash
git clone https://github.com/auropro-hyd/Agentic_Accelerators.git
cd Agentic_Accelerators
bash apps/dla/scripts/install.sh
```

The install script cds to the workspace root, runs `uv sync --all-packages`
(populating the shared `.venv` at the repo root), and registers the package for
editable use so `uv run dla` finds the source under `apps/dla/src/dla/`.

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

## Auto-drafted descriptions (M3)

`dla describe` drafts a plain-language description for every table and
column, grounded in the discovered schema and the M2 profile evidence
— it does not invent facts. Each draft records the model, the prompt
version, the grounding fields it used, and a grounding hash, so re-runs
that find unchanged evidence cost nothing and reviewer edits are never
overwritten.

```bash
# Preview the exact prompt for one column without calling a model:
uv run dla describe --config config/examples/postgres_minimal.yaml \
  --column "column:public.orders:status" --mode dry-run

# Draft every table + column (the model provider is config-driven):
uv run dla describe --config config/examples/postgres_minimal.yaml --mode live

# Re-run: unchanged grounding is skipped (idempotent), no tokens spent.
```

The model is selected entirely in configuration (see
[Configuration](#configuration)) — a local model for cost-free
development, or any hosted provider for an engagement, with no code
change. A reviewer can edit a draft's markdown body and run
`dla describe --commit-edits` to lock the edit in; the writer then
protects it from any future re-draft.

## Web review interface (M4)

`dla ui` serves a local, single-user review interface over the bundle.
Reviewers browse tables and columns, see each description with its
confidence and the evidence behind it, edit or accept drafts in place,
work a confidence-prioritized review queue, and bulk-accept the
high-confidence drafts in a table. Every save writes straight back to
the same markdown files — there is no separate database, and edits made
in the browser and in an editor are interchangeable.

```bash
uv run dla ui --config config/examples/postgres_minimal.yaml
# serves http://127.0.0.1:8765 and opens a browser

# Record who is reviewing (stamped on each edit):
export DLA_SME_NAME="Data Steward"
uv run dla ui --config config/examples/postgres_minimal.yaml --no-browser --view review-queue
```

The interface binds to a local address only; it has no network-exposed
host option and no authentication layer (single-user, local use).
Description text entered in the browser is HTML-escaped on render.

## Client-documentation import and reconciliation (M5)

When a client already has documentation — a CSV/Excel data dictionary,
structured markdown notes, or a dbt `manifest.json` — `dla import`
pulls it in as `client-provided` artifacts, kept separate from the
auto-drafts. `dla reconcile` then classifies every imported item
against the discovered schema into four buckets: **match** (doc and
data agree), **conflict** (they disagree, e.g. a type mismatch),
**gap-doc-only** (documented but not in the schema), and
**gap-source-only** (in the schema but undocumented). A reviewer
resolves conflicts side-by-side in the web interface.

```bash
# Import a dbt manifest (read as plain JSON — no code is ever executed):
uv run dla import --config config/examples/postgres_minimal.yaml \
  --dbt-manifest path/to/manifest.json

# Import a folder of CSV/Excel dictionaries and/or markdown notes:
uv run dla import --config config/examples/postgres_minimal.yaml \
  --client-docs path/to/client_docs/

# Classify every imported item against the discovered schema:
uv run dla reconcile --config config/examples/postgres_minimal.yaml
uv run dla reconcile --config config/examples/postgres_minimal.yaml --bucket conflict

# Resolve conflicts in the browser:
uv run dla ui --config config/examples/postgres_minimal.yaml --view imports/conflicts
```

When a reviewer settles a conflict, the imported item is marked
`client-provided-reconciled` and the chosen text is written as the
column's description, with a `prior_sources` audit trail recording both
the documented value and the discovered evidence it was chosen over.

## Business glossary and pattern catalog (M6)

`dla glossary build` scans the discovered schema for terms that recur
across tables and columns, proposes each term that meets a recurrence
threshold, and drafts a plain-language definition for it. `dla patterns
detect` runs the structural detectors over the schema and records the
shapes it finds — star, snowflake, junction, and audit-column patterns —
under `patterns/`.

```bash
# List recurring terms without calling a model:
uv run dla glossary build --config config/examples/postgres_minimal.yaml --mode dry-run

# Draft a definition for each term (model provider is config-driven):
uv run dla glossary build --config config/examples/postgres_minimal.yaml --mode live

# Propose only terms that appear at least four times:
uv run dla glossary build --config config/examples/postgres_minimal.yaml --min-recurrence 4

# Detect structural patterns over the discovered schema:
uv run dla patterns detect --config config/examples/postgres_minimal.yaml
```

Glossary drafting is idempotent the same way `describe` is: a re-run that
finds unchanged usages costs nothing (pass `--force` to re-draft anyway).

## KPI workbook and review coverage (M7)

`dla kpi add` records a subject-matter expert's KPI definition in the
workbook under `kpi/`: each entry captures the formula, its grain, the
owner, the source tables it draws from, and the **dimensions it can be
sliced by** — each dimension is resolved to a discovered column (and
rejected if missing or ambiguous), so a downstream consumer can enumerate
"metric × dimension" combinations without guessing. `dla hierarchy add`
records a dimension's drill-down order (year → quarter → month), each
level validated against the schema. `dla coverage` reports how much of
the bundle a reviewer has signed off on, broken down per artifact type.

```bash
# Add a KPI to the workbook (all listed flags are required):
uv run dla kpi add --config config/examples/postgres_minimal.yaml \
  --name monthly_active_customers \
  --definition "Distinct customers with an order in the trailing 30 days" \
  --formula "count(distinct customer_id)" \
  --grain "one row per calendar month" \
  --owner "Data Steward" \
  --source-tables "public.orders,public.customers" \
  --dimensions "region,order_date"

# Record a drill-down hierarchy (levels coarsest → finest):
uv run dla hierarchy add --config config/examples/postgres_minimal.yaml \
  --name date_rollup --dimension date \
  --level "year=public.orders.order_date" \
  --level "month=public.orders.order_date"

# Report review coverage per artifact type:
uv run dla coverage --config config/examples/postgres_minimal.yaml
uv run dla coverage --config config/examples/postgres_minimal.yaml --format json
```

M7 also carries SME work forward across engagements: term-mapping rules
(kept under `term_mappings/`, they outrank fuzzy reconciliation matching)
and prior-bundle import, so definitions settled once do not have to be
re-derived.

## Full pipeline and strategy recommendation (M8)

`dla run` drives the whole pipeline from a clean source to a validated
bundle in one command: discover, profile, readiness, patterns, recommend,
and validate, plus the two LLM-gated steps (describe, glossary) when
`--llm` is set. Progress is recorded to `bundle/.run_state.json` after
each step, so a failed or interrupted run can be resumed.

`dla recommend` then reads the whole bundle and picks a downstream
retrieval strategy — `plain_schema`, `vector`, or `knowledge_graph`. The
decision is **deterministic**: no model sits in the decision path, so the
same bundle always yields the same recommendation. `dla bundle
export-schema` publishes the machine-readable JSON Schema from the
in-process models, and `dla bundle validate` checks every artifact against
the contract.

```bash
# Offline pipeline: discover .. recommend .. validate
uv run dla run --config config/examples/postgres_minimal.yaml

# Also draft descriptions + glossary (needs an LLM credential):
uv run dla run --config config/examples/postgres_minimal.yaml --llm

# Resume after the last completed step, or start at a named step:
uv run dla run --config config/examples/postgres_minimal.yaml --resume
uv run dla run --config config/examples/postgres_minimal.yaml --from-step patterns

# Skip a step, or halt before describe if readiness is critical:
uv run dla run --config config/examples/postgres_minimal.yaml --skip-step glossary
uv run dla run --config config/examples/postgres_minimal.yaml --stop-on-readiness-critical

# Inspect the recommendation with its reasoning and alternatives:
uv run dla recommend --config config/examples/postgres_minimal.yaml --explain

# Record an SME override (both flags required):
uv run dla recommend --config config/examples/postgres_minimal.yaml \
  --override knowledge_graph --reason "Client needs entity-level traversal"

# Publish the schema and validate the bundle against the contract:
uv run dla bundle export-schema --out config/schemas/bundle-schema.json
uv run dla bundle validate --config config/examples/postgres_minimal.yaml
uv run dla bundle validate --config config/examples/postgres_minimal.yaml --strict
```

The `dla run` pipeline closes by validating the bundle against the
contract, so a clean run ends with a hand-off-ready deliverable: the
bundle directory, the generated `bundle-schema.json`, and the
deterministic recommendation. `knowledge_graph` routes to the
knowledge-graph accelerator, `vector` to the vector/semantic layer,
`plain_schema` to straight relational modeling.

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
| `dla profile --config <yaml>`                                          | For every column already in the bundle, sample, compute stats, and write a profile artifact. On Postgres, tables larger than `sample_budget_rows` are sampled with `TABLESAMPLE SYSTEM ... REPEATABLE` (spread across the table, deterministic across re-runs; the profile records a `sampling_note`) instead of just the first N rows. |
| `dla profile --config <yaml> --mode full_scan`                         | Profile by reading every row (exact stats; slower than the default sampling mode).                                 |
| `dla profile --config <yaml> --table <schema.table>`                   | Restrict profiling to one table — useful after a schema change.                                                    |
| `dla readiness --config <yaml>`                                        | Walk the bundle, detect data-quality issues, write `bundle/readiness/issues/*` and `bundle/readiness/readiness.md`. |
| `dla readiness --config <yaml> --severity {critical,warning,info,all}` | Restrict terminal output to a severity (the full report is still written to disk).                                 |
| `dla describe --config <yaml> --mode {dry-run,live}`                   | Auto-draft descriptions for tables and columns; `dry-run` prints the prompt without calling a model.                |
| `dla describe --config <yaml> --column <id> \| --table <name>`         | Restrict drafting to one column or one table.                                                                     |
| `dla describe --config <yaml> --commit-edits`                          | Detect reviewer-edited description bodies and lock them in (provenance becomes `ai-drafted-edited`).                |
| `dla ui --config <yaml>`                                               | Serve the local web review interface at `127.0.0.1:8765` (flags: `--port`, `--view`, `--no-browser`).             |
| `dla import --config <yaml> --client-docs <path>`                      | Import a CSV/Excel dictionary and/or markdown notes (file or folder) as `client-provided` artifacts.               |
| `dla import --config <yaml> --dbt-manifest <path>`                     | Import a dbt `manifest.json` (parsed as plain JSON; no code is executed).                                           |
| `dla reconcile --config <yaml>`                                        | Classify every imported artifact against the discovered schema into match / conflict / gap buckets.                |
| `dla reconcile --config <yaml> --bucket <name>` / `--auto-confirm-matches` | List one bucket, or accept all `match` items in bulk.                                                          |
| `dla glossary build --config <yaml> --mode {live,dry-run}`             | Extract recurring schema terms and draft a definition for each (flags: `--min-recurrence`, `--force`).            |
| `dla patterns detect --config <yaml>`                                  | Run all structural detectors over the schema and write `bundle/patterns/*` (star, snowflake, junction, audit).     |
| `dla kpi add --config <yaml> --name --definition --formula --grain --owner --source-tables` | Add (or update) a KPI in the workbook (optional: `--formula-kind`, `--dimensions`). Dimensions are resolved to discovered columns and rejected if missing/ambiguous; `--skip-dimension-validation` records conceptual dimensions as labels only. |
| `dla hierarchy add --config <yaml> --name --level name=schema.table.column ...`             | Record a dimension drill-down hierarchy (levels coarsest→finest, each validated to a discovered column; optional: `--dimension`, `--description`). |
| `dla coverage --config <yaml> --format {table,json}`                   | Report SME review coverage per artifact type.                                                                     |
| `dla recommend --config <yaml> --explain`                              | Recommend a downstream strategy (`plain_schema` / `vector` / `knowledge_graph`); `--explain` prints reasoning, signals, and alternatives. |
| `dla recommend --config <yaml> --override <strategy> --reason <text>`  | Record an SME override of the recommended strategy (both flags required).                                          |
| `dla bundle export-schema --out <path>`                                | Write the published JSON Schema from the in-process pydantic models.                                              |
| `dla bundle validate --config <yaml>` / `--bundle-dir <path>` / `--strict` | Validate every artifact against the contract; `--strict` treats warnings as failures too.                     |
| `dla run --config <yaml>`                                              | Run the full pipeline (discover .. recommend .. validate) end to end; offline unless `--llm` is set.              |
| `dla run --config <yaml> --llm --from-step <step> --skip-step <step> --resume --stop-on-readiness-critical` | Enable LLM steps, control the plan, resume after the last completed step, or halt on a critical readiness issue. |

Help for any subcommand:

```bash
uv run dla discover --help
uv run dla describe --help
uv run dla ui --help
uv run dla import --help
uv run dla reconcile --help
```

---

## Exit codes

CI gates and scripts can branch on the kind of failure.

| Code | Meaning                                                                            |
| ---- | ---------------------------------------------------------------------------------- |
| 0    | Success.                                                                           |
| 1    | Generic error.                                                                     |
| 2    | Connection / source / LLM-provider transport failure.                              |
| 3    | Config or usage error.                                                             |
| 4    | Resource not found (artifact / path / table / column).                             |
| 5    | Validation failure (bundle-contract validation, or an unparseable LLM response).   |
| 6    | User-cancelled / nothing to resume.                                                |
| 7    | Halted by policy (readiness-critical stop via `--stop-on-readiness-critical`).     |

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

llm:                                       # used by `dla describe` (M3)
  provider: ollama                         # ollama (local) / openai / anthropic / azure / ...
  model: llama3.2                          # model or deployment name
  api_base: null                           # provider endpoint, when applicable
  api_version: null                        # required for Azure OpenAI (e.g. 2024-02-15-preview)
  api_key_env_var: DLA_LLM_API_KEY         # API key is read from this env var; never stored in YAML
  timeout_seconds: 60
  max_retries: 2

ui:                                        # used by `dla ui` (M4)
  host: 127.0.0.1                          # local-only by design
  port: 8765
  sme_name_env_var: DLA_SME_NAME           # reviewer identity stamped on edits, read from this env var
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

### Model provider (LLM)

`dla describe` reaches the model through a provider-agnostic gateway,
so switching providers is a configuration change, not a code change:

- **Local model** (default): a locally hosted model — cost-free,
  reproducible, and nothing leaves the machine. Ideal for development.
- **Hosted provider**: set `provider`, `model`, `api_base`, and (for
  Azure) `api_version`; the API key is read from the environment
  variable named in `api_key_env_var`.

A template configuration for a hosted provider ships at
`config/examples/azure_openai.yaml` (placeholders only — fill in your
own endpoint and deployment, and export the key).

### Secrets

Passwords, API keys, and tokens are **never** stored in YAML. The
config names the environment variable to read each from
(`postgres.password_env_var`, `llm.api_key_env_var`), and the loader
fails fast with exit code 3 if a required variable is unset.

---

## Project structure

```text
.                                 # apps/dla/ (within the Agentic_Accelerators workspace)
├── config/                       # default + example YAML configs
│   ├── default.yaml
│   └── examples/
├── scripts/install.sh            # one-shot dev environment setup (cds to workspace root)
├── src/dla/                      # all source code
│   ├── bundle/                   # on-disk format: schema, layout, provenance, reader, writer
│   ├── cli/                      # Typer CLI entrypoints (discover, profile, readiness, describe, ui, import, reconcile, glossary, patterns, kpi, coverage, recommend, bundle, run, version)
│   ├── config/                   # pydantic config models + loader
│   ├── connectors/               # Postgres, CSV (extensible to other providers)
│   ├── discovery/                # schema introspection, relationship inference, confidence tagging
│   ├── profiling/                # samplers, statistics, profile engine
│   ├── readiness/                # data-quality checks, severity, report assembly
│   ├── prompts/                  # versioned prompt templates + registry (M3)
│   ├── describe/                 # auto-draft engine: grounding, idempotency, edit preservation (M3)
│   ├── web/                      # local review interface: FastAPI app, routes, templates, static (M4)
│   ├── importers/                # CSV/Excel, markdown, dbt-manifest importers + normalizer (M5)
│   ├── reconciliation/           # matcher, classifier, resolver (M5)
│   ├── glossary/                 # recurring-term extraction + definition drafting (M6)
│   ├── patterns/                 # structural detectors: star, snowflake, junction, audit (M6)
│   ├── kpi/                      # KPI workbook models + writer (M7)
│   ├── hierarchy/                # dimension drill-down hierarchies (M7 extension)
│   ├── coverage/                 # SME review-coverage analysis (M7)
│   ├── recommender/              # deterministic strategy recommender (M8)
│   └── orchestrator/             # end-to-end pipeline runner + resumable run state (M8)
│   # Note: LLM gateway (llm/) and logging/config (logging_ctx/) have been extracted
│   # into workspace packages: auropro-llm (libs/llm) and auropro-core (libs/core).
└── tests/
    ├── fixtures/
    │   ├── postgres/             # docker-compose + seed SQL (clean + quality-issues seeds)
    │   ├── csv/                  # synthetic CSV files
    │   ├── client_docs/          # CSV dictionary + markdown notes (M5)
    │   └── dbt/                  # sample dbt manifest.json (M5)
    ├── unit/                     # fast unit + TestClient suite
    ├── integration/              # import / reconciliation flows
    ├── eval/                     # reconciliation bucketing accuracy
    └── ui/                       # browser end-to-end (opt-in marker)
```

---

## Development

### One-time setup

```bash
# from the workspace root (Agentic_Accelerators/):
bash apps/dla/scripts/install.sh
```

This cds to the workspace root and wraps:

```bash
uv sync --all-packages   # populates shared .venv at workspace root
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

### Test suite

```bash
uv run pytest tests -q            # full suite
uv run pytest tests/unit -q       # fast unit + TestClient subset
```

The suite covers the M1 substrate, the provenance state machine, the
bundle writer, profiling statistics, readiness checks, the
configuration loader, the LLM gateway, the auto-draft engine, the web
review interface (via an in-process test client), the client-doc
importers, and reconciliation — plus a reconciliation bucketing-accuracy
eval.

Browser end-to-end tests under `tests/ui/` use the `ui` marker and are
skipped automatically unless a browser is installed; run them
explicitly with `uv run pytest -m ui`.

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
| `ModuleNotFoundError: No module named 'dla'`             | Editable-install `.pth` file not registered                         | Re-run `bash apps/dla/scripts/install.sh` from the workspace root                                                               |
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
| **M3**    | Auto-drafted descriptions grounded in discovered facts and profiles; markdown review loop with edit preservation | Released   |
| **M4**    | Local web interface for reviewing and editing drafts                                                  | Released   |
| **M5**    | Client-documentation import (CSV / Excel / dbt manifest) with reconciliation against discovered evidence | Released   |
| **M6**    | Cross-engagement glossary and pattern catalog (audit, junction, lookup, etc.)                         | Released   |
| **M7**    | KPI workbook, review-coverage analysis, prior-bundle import, and SME term mapping                     | Released   |
| **M8**    | Deterministic strategy recommender, published bundle JSON schema, and end-to-end pipeline orchestrator | Released   |

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
