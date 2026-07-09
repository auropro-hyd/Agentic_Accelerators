# v1 Delivery — Deferred Scope & Known Deviations

This is the honest, single record of where the delivered v1 (Milestones M1–M8)
deviates from the original specification (`specs/001-data-layer-accelerator/`)
and scope (`docs/Accelerators_Scope_v5.md`). Every item here is a *tracked*
decision, not a silent gap. It exists so a reader of the spec is never misled
about what shipped.

Status legend: **Deferred** (planned, not built) · **Backlog** (should be built
before calling the engine production-hardened) · **Changed** (built differently
than the plan, deliberately).

## Deferred (planned, not in v1)

| Item | Spec anchor | Why / status |
|------|-------------|--------------|
| **Snowflake connector** | FR-001; Scope v5 | Only Postgres + CSV connectors ship. The connector abstraction (`connectors/base.py`) is provider-agnostic and Snowflake-ready; the adapter itself is deferred (no `connectors/snowflake.py`, no `snowflake_demo.yaml`). Pull in when a Snowflake engagement is scheduled. FR-001 has been annotated accordingly. |
| **Slowly Changing Dimension (SCD) pattern detection** | US 6.2; Scope v5 | The four higher-leverage patterns (star, snowflake, junction, audit) ship and gate SC-005. SCD was deferred in the M6 course-correction and did not land in M8. Add as a 5th detector when signals show it's the bottleneck. |

## Backlog (build before "production-hardened")

| Item | Spec anchor | Why / status |
|------|-------------|--------------|
| **Real-database / end-to-end integration tests** | SC-001/002/009/012 | A Postgres compose + seed exists, but tests run against hand-seeded in-memory bundles. The full `dla run` against a live Postgres (and the <30s discovery / <2min profile / <10min pipeline perf numbers) is not yet exercised in CI. Highest-value hardening item. |
| **Description-quality eval (LLM-as-judge)** | SC-003 / FR-026 / Constitution VII | Reconciliation and glossary-extractor evals exist; the description eval (20 goldens, judge ≥4/5 on ≥70%) does not. The flagship AI output currently ships without its measurement gate. |
| **`INSUFFICIENT_SIGNAL` for descriptions** | FR-011 / US 3.2 | Implemented for the glossary generator only. The describe engine surfaces low-confidence columns via the review queue (Weak/unprofiled/readiness ordering) rather than emitting the sentinel. Behavioural workaround, not the spec's literal contract. |
| **`type_mismatch` readiness check** | FR-007 | **Done (L1 hardening, Wave 4).** A relationship whose endpoint columns have mismatched normalized types now raises a `type_mismatch` Warning (`readiness/checks.py::check_type_mismatch`). |
| **Chunked-fetch / OOM guard in profiling** | tasks T059 | Large-column profiling has no streaming guard; low risk on current fixtures. |

## Changed (built differently, on purpose)

| Item | Original plan | What shipped | Rationale |
|------|---------------|--------------|-----------|
| **Repository shape** | `plan.md`: "not a monorepo; one Python distribution" | uv workspace monorepo — `apps/dla` + `libs/core` (auropro-core) + `libs/llm` (auropro-llm), per-package CI/coverage/release | Superseded by the approved `docs/ACCELERATOR-REPO-PLAN.md`. `plan.md`'s Structure Decision is therefore historical. |
| **dbt manifest import** | `plan.md`: `dbt-artifacts-parser` library | Plain-JSON parse, no library, no code/Jinja eval | Security hardening — never execute client content. Recorded in M5. |
| **Prompt registry** | `prompt-contract.md`: `.md`-with-frontmatter files, prose output, `dla/llm/prompt_registry.py`, `prompt_version` = `describe_column@v1` | Jinja `.j2` templates returning structured JSON, `dla/prompts/registry.py`, `prompt_version` = `column_v1` | Implementation predates the contract; the contract has not been reconciled. Tracked below. |

## Contract-doc reconciliations still open

These are documentation-vs-code drifts to reconcile (the code is the shipped
truth; the contracts lag):

- `contracts/prompt-contract.md` describes a different prompt design than shipped (see table above).
- `contracts/cli-commands.md` still lists some pre-implementation flags (`dla describe --target/--regenerate`, `dla glossary review`, global `--source-id`) and omits shipped ones (`dla run --llm/--resume`, `dla version`, `dla readiness --offline`, `--mock-response`, `bundle --strict/--out`). Exit codes were reconciled (2026-07).
- `contracts/web-ui-contract.md` lists page routes not yet built: `/glossary`, `/patterns`, `/imports`, `/readiness`, and two partials (`/partials/review-queue/next`, `/partials/grounding-signals/{id}`).
- The generated `bundle-schema.json` advertises `coverage_record` in its artifact-type enum but intentionally has no persisted payload for it (E13 coverage is computed on demand). A parity test now encodes this exception.

## What is genuinely done to spec

M1–M8 all demo real code; the bundle writer (atomicity + provenance state
machine), connectors (Postgres/CSV), profiling, describe idempotency + SME
preservation, reconciliation, glossary, the four patterns, KPI workbook,
coverage, prior-bundle import, term-mapping precedence, the **deterministic
strategy recommender (now with a 10-fixture SC-006 eval)**, the published +
version-pinned bundle contract, and the resumable `dla run` orchestrator are all
implemented and unit-tested. The deficit above is concentrated in real-DB/e2e
proof, two eval gates, and contract-doc reconciliation.
