# Data Layer Accelerator (`dla`)

The **Knowledge Creation Workbench** piece of the Agentic Application Accelerator
suite. Point it at a client's data source; it discovers, profiles, describes,
reconciles, and packages everything into a versioned `bundle/` directory that
downstream agents and humans can consume.

## What it produces

Every artifact appears as a paired markdown + JSON file under `bundle/`. The
markdown is the human-editable source of truth; the JSON is the machine view.
Provenance and confidence are tagged on every artifact.

```
bundle/
├── source.{md,json}
├── schema/{tables,columns,relationships,indexes}/*.{md,json}
├── profiles/*.{md,json}
├── readiness/issues/*.{md,json}
├── descriptions/{tables,columns}/*.{md,json}
├── glossary/*.{md,json}
├── patterns/*.{md,json}
├── kpi/*.{md,json}
├── imports/{artifacts,reconciliation}/...
├── recommendation/recommendation.{md,json}
└── coverage/coverage.json
```

## Quickstart

```bash
# 1. Install (Python 3.11+, uv recommended)
uv sync

# 2. Bring up the fixture Postgres
docker compose -f tests/fixtures/postgres/docker-compose.yaml up -d

# 3. Discover the fixture source into a bundle
uv run dla discover --config config/examples/postgres_minimal.yaml
```

## Project scope and roadmap

See `docs/Accelerators_Scope_v5.md` for the published scope. The internal
milestone plan and feature spec live in `specs/001-data-layer-accelerator/`
and `Local_Dev/` (gitignored).
