# DLA Bundle Contract

The **bundle** is the Data Layer Accelerator's single deliverable: a directory of
paired markdown + JSON artifacts that fully describes a client's data source and
recommends how the downstream agentic layers should consume it. This document is
the public, human-readable contract for that directory. The machine-readable
companion is [`apps/dla/config/schemas/bundle-schema.json`](../apps/dla/config/schemas/bundle-schema.json),
generated directly from the pydantic models via `dla bundle export-schema` — so
the schema can never drift from the code.

> **Consumers:** the layers above L1 (assembler, knowledge-graph, vector/semantic
> accelerators) read this contract. Every artifact is JSON, self-describing via
> `artifact_type`, and carries provenance so a consumer can tell discovered fact
> from AI draft from SME-authored truth.

## Layout

```text
bundle/
├── bundle.json                 # manifest: schema_version, source_id, artifact_counts, last_run_at
├── source.md / .json           # the data source
├── schema/
│   ├── tables/                 # one file per table
│   ├── columns/                # one file per column
│   ├── relationships/          # declared + inferred FKs / join keys
│   └── indexes/
├── profiles/                   # per-column profile (nulls, distinct, samples, quantiles)
├── readiness/
│   ├── readiness.md            # human summary
│   └── issues/                 # one file per data-quality issue
├── descriptions/{tables,columns}/   # AI-drafted / SME-edited prose
├── glossary/                   # recurring business terms
├── patterns/                   # detected star/snowflake/junction/audit shapes
├── kpi/                        # SME-authored KPI workbook entries
├── term_mappings/              # SME term-mapping rules (outrank fuzzy matching)
├── imports/{artifacts,reconciliation}/   # client-doc import + reconciliation
├── recommendation/             # the strategy recommendation (one per run)
└── .run_state.json             # orchestrator step state (resume support)
```

## Common fields (every artifact)

| Field | Notes |
|-------|-------|
| `artifact_id` | Stable id, `"<type>:<qualified-name>"`. No whitespace. |
| `artifact_type` | Discriminator — one of the types below. |
| `source_id` | The engagement's source. |
| `provenance` | See the state machine below. |
| `confidence` | `Explicit` / `Strong` / `Weak` (where applicable). |
| `created_at` / `updated_at` | ISO-8601 UTC. Idempotent re-runs preserve `created_at`. |
| `created_by` | `accelerator` / `sme` / `importer` / `prior-bundle-import`. |
| `grounding_signals` | Evidence the value was derived from (nullable). |
| `imported_from`, `prior_sources` | Set when inherited from a prior bundle. |

### Provenance state machine

`discovered` and `client-provided` are entry states; SME/LLM work moves an
artifact forward. Transitions are enforced on every write; anything not listed is
rejected.

```
discovered                 → discovered | sme-authored
client-provided            → client-provided | client-provided-reconciled | sme-authored
client-provided-reconciled → client-provided-reconciled | sme-authored
ai-drafted                 → ai-drafted | ai-drafted-edited | sme-authored
ai-drafted-edited          → ai-drafted-edited | sme-authored
sme-authored               → sme-authored
```

Artifacts at `ai-drafted-edited`, `sme-authored`, or `client-provided-reconciled`
are **preserved** — a re-run never clobbers human work.

## Artifact types

`source`, `table`, `column`, `relationship`, `index`, `profile`,
`readiness_issue`, `description`, `glossary_entry`, `pattern`, `kpi`,
`imported_artifact`, `reconciliation_result`, `term_mapping_rule`,
`recommendation`. Field-level detail for each is in the generated JSON Schema
(`$defs`).

### Recommendation (M8)

One per recommender run, at `recommendation/`. **Deterministic** — no LLM in the
decision path (FR-018), so the same bundle always yields the same recommendation.

| Field | Notes |
|-------|-------|
| `recommended_strategy` | `plain_schema` / `vector` / `knowledge_graph`. |
| `strategy_confidence` | `high` / `medium` / `low`. |
| `reasoning` | Plain-language explanation of the choice. |
| `signals_detected` | `{schema_size, pattern_summary, text_field_count, rel_density, coverage_pct, kpi_count, …}`. |
| `alternatives_considered` | `[{strategy, why_not}]` for the two not chosen. |
| `coverage_warning` | Set when low review coverage reduced confidence (FR-023). |
| `override` | `{chosen_strategy, override_reason, overridden_by, overridden_at}` when an SME overrides. |

The strategy is the hand-off signal to the layers above L1:
`knowledge_graph` → the knowledge-graph accelerator; `vector` → the
vector/semantic layer; `plain_schema` → straight relational modeling.

## Validation

```bash
dla bundle export-schema            # regenerate config/schemas/bundle-schema.json
dla bundle validate -c <config>     # every artifact must round-trip its model
dla bundle validate -c <config> --strict   # warnings fail too
```

`validate` reports **errors** (malformed artifact, KPI referencing a missing
table, missing manifest — exit code 4) and **warnings** (undescribed table, no
recommendation yet). It is a security gate as much as a quality gate: an artifact
that does not match the contract — e.g. a value injected through a grounding
signal — never ships.
