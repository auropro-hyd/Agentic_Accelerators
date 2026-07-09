# L1 (dla) Large-Fixture End-to-End Validation Report

Date: 2026-07-09 · Branch: `chore/makefile-cross-platform` (isolated worktree)
Environment: macOS, Python 3.11, uv workspace, Docker postgres:16-alpine

## 1. Fixture summary

New fixture at `apps/dla/tests/fixtures/postgres_large/` (compose + 8 seed files +
README). Container `dla_fixture_postgres_large`, host port **55433** (the existing
15-table fixture on 55432 is untouched). Configs:
`apps/dla/config/examples/postgres_large.yaml` (all 5 schemas → `./bundle_large`)
and `postgres_large_staging_only.yaml` (no-FK schema only → `./bundle_staging`).

- **125 tables / 673 columns / 5 schemas**, ~130k rows total.
- `sales` (26): star #1 — 4 facts on conformed dims, two snowflake chains
  (product→subcategory→category→department; store→region→country→continent),
  3 bridge tables, 2 text-heavy tables, composite-PK facts.
- `finance` (21): star #2 — self-referencing `dim_accounts`, 4 composite PKs,
  **multi-column FK** (ledger→fiscal_periods), cross-schema FK (→hr.employees),
  2 junctions, text-heavy audit journal.
- `hr` (16): self-referencing `employees.manager_id`, 3 junctions, enum column,
  **110-column wide table**, composite-PK job history.
- `staging` (16): **no-FK zone** — 0 declared FKs; engineered joins for
  inference (overlap, type-mismatch, orphaned, unmatchable naming), 2 PK-less tables.
- `analytics` (46): reserved-word `"order"` (cols `"select"`, `"group"`),
  mixed-case `"CamelCaseEvents"`, 60-char identifiers, `typed_showcase`
  (uuid/jsonb/numeric[]/text[]/enum/interval/bytea/inet/daterange), 100k-row
  `events_tall`, zero-row table, **25 generated distractors** all shaped
  `(id, name, status, created_at)`, 6 quality-issue tables (incl. a **declared
  broken FK via `NOT VALID`** and a mixed-case status column).

## 2. Results per command

| # | Command | Wall time | Exit | Verdict |
|---|---------|-----------|------|---------|
| 1 | `discover --dry-run` | 37.9s cold / ~1.5s warm | 0 | PASS (see A1 count anomaly) |
| 2 | `discover` | **1.49s** | 0 | PASS w/ anomalies A1 |
| 3 | `profile` (sampling) | **13.4s** (667 ok, 6 errors) | 0 | FAIL-partial → D2 |
| 4 | `profile --table analytics.order` / `"CamelCaseEvents"` | 0.9s | 0 | PASS (quoted/reserved OK) |
| 5 | `profile --table sales.no_such_table` | 0.6s | **0** | FAIL → D7 (silent no-op, expected exit 4) |
| 6 | `readiness` | 3.9s | 0 | PASS — all seeded issues found (see §4) |
| 7 | `patterns detect` | 0.8s | 0 | PASS w/ misclassifications → D12 |
| 8 | `glossary build --mode dry-run` | ~1s | 0 | PASS w/ term noise → D14 |
| 9 | `describe --table hr.employee_survey_wide --mode dry-run` | ~1s | 0 | PASS w/ formatting bug → D15 |
| 10 | `describe --column column:analytics.order:select --mode dry-run` | ~1s | 0 | PASS (sane prompt) |
| 11 | `kpi add` (valid ×2) | <1s | 0 | PASS |
| 12 | `kpi add` (ghost tables) | <1s | 4 | PASS — rejected, not written |
| 13 | `kpi add` (valid table, fake dims + fake formula col) | <1s | 0 | accepted — dims/formula are free text (see §6) |
| 14 | `recommend --explain` (full) | 0.5s | 0 | PASS — result analyzed in §5 |
| 15 | `recommend --override knowledge_graph --reason …` | 0.5s | 0 | PASS (attributed to default `developer`) |
| 16 | `bundle validate` / `--strict` | 0.5s | 0 / 5 | PASS (125 warnings; strict exits 5) but → D1b |
| 17 | `bundle export-schema` | <1s | 0 | PASS (63KB schema) |
| 18 | `run` (clean dir, offline) | **17.4s** | 0 | PASS (discover 0.8 / profile 12.4 / readiness 3.7 / patterns+recommend+validate ~0.12) |
| 19 | `run` + SIGINT mid-profile | — | 0 | FAIL → D3 (SIGINT swallowed; run completes) |
| 20 | `run` + SIGTERM, then `run --resume` | 16.5s | 0 | PASS — resumed exactly `profile…validate` |
| 21 | `run --resume` with nothing left | 0.4s | 6 | PASS (documented exit 6) |
| 22 | Idempotency: re-run 7 commands, stat+diff 3,350 files | ~25s | diff=0 | **PASS — zero diffs, not even mtimes** |
| 23 | `import --client-docs` (9-row fabricated CSV dictionary) | <1s | 0 | PASS |
| 24 | `reconcile` / `--bucket match` | 0.5s | 0 | PASS w/ conflict gap → D8 |
| 25 | `coverage` / `--format json` | <1s | 0 | PASS (imported 0/9, kpi 2/2) |
| 26 | staging-only `run` + `recommend --explain` | 1.25s | 0 | PASS — result in §5 |
| 27 | discover with password env var unset | — | **2** | DEVIATION → D6 (docs promise fail-fast exit 3) |
| 28 | `describe --column <nonexistent>` | <1s | 4 | PASS (clean artifact-not-found) |

Term mappings: no CLI surface exists (bundle dir + reconciliation precedence only) — nothing to exercise offline beyond reconcile.

## 3. Performance

- **connect + discover + profile on 125 tables / 673 cols: ~15s** (org target < 2h — beaten by ~480×). Full offline pipeline: 17.4s.
- Tall table (100k rows): profiled within the 10,000-row budget; sample is the **head of the table** (values 1…10000), i.e. LIMIT-style, not random — sampling-bias caveat for skewed data.
- Bundle size: **13MB, 3,350 files** (full); staging-only 1.3MB.
- Cold-start outlier: the very first CLI invocation took 37.9s (uv first-run + cold container); all subsequent invocations 0.4–13s.

## 4. Readiness vs seeded ground truth (10 critical / 3 warning / 58 info)

| Seeded issue | Detected? |
|---|---|
| Q1 empty tables ×2 | YES — both Critical |
| Q2 all-null columns ×2 | YES — both Critical |
| Q3 constant columns ×2 | YES — Info (plus 56 incidental true constants, mostly same-instant `created_at` defaults — correct but noisy at scale) |
| Q4 high-null 70% | YES — Warning (plus 2 genuine incidental: `fact_sales.promotion_id` 0.8, `job_history.ended_on` 0.67) |
| Q5 broken FK on **inferred** rel | YES — Critical, 40 orphans sampled |
| Q6 broken FK on **declared `NOT VALID`** FK | YES — Critical (declared rels are value-checked too) |
| Q8 staging orphan join | YES — Critical |
| Q7 mixed-case status ('active'/'Active'/'ACTIVE') | NO — as expected; no case-consistency check exists. `type_mismatch` confirmed absent (deferred, matches docs/v1-deferred-scope) |

False positive: the deliberate varchar↔int join (`stg_shipments.stg_order_id`) is reported as a Critical broken_fk with **350/350 orphans** — values are equal but compared as `'2' ≠ 2` (no type coercion) → D5.
Gap: the 6 jsonb/array columns whose profiles errored produce **no readiness issue at all** (only `unprofiled` status is surfaced; `error` status is invisible) → part of D2.

## 5. Recommendation outputs

**Full 5-schema bundle** (11 junctions, 88 rels, 6 prose columns):
- Strategy: **vector**, confidence medium. vector 6 pts (6 free-text cols ≥3; avg 298 chars ≥200) vs knowledge_graph 4 pts (11 junctions ≥2; ≥1 bridge) vs plain 1.
- KG lost its +2 density bonus because rel_density 0.704 < threshold — the 125-table denominator (distractors + no-FK schema) dilutes density. **Structural insight: vector and KG both max at 6 points and ties break toward vector, so a junction-rich schema can never out-rank a text-rich schema** — the "junctions ⇒ knowledge_graph" behavior seen on the small fixture does not generalize → D4.
- `coverage_pct: 1.0` reported with zero review work done (empty coverage = full coverage) → D17.

**Staging-only (no-FK) bundle** (16 tables, 9 inferred-only rels):
- Strategy: **plain_schema**, confidence **low**; plain 1 vs KG 1 vs vector 0 — a bare tie broken by precedence. Inferred rels fully feed rel_density (0.562) and one inferred "junction" (`stg_inventory`, actually a fact) feeds the KG score. A cloud-warehouse dump with obvious entity joins lands on the least-capable strategy at low confidence.

**Override**: recorded cleanly (`recommender chose: vector / SME override: knowledge_graph`), attributed to default `developer` when `DLA_SME_NAME` is unset.

## 6. Defects and anomalies (ranked)

**P1 — correctness of the contract deliverable**
- **D1. Manifest counts are wrong on multi-schema sources.** `bundle.json` says 130 tables / 703 cols / 92 rels / 5 idx; disk has 125 / 673 / 88 / 4. Cause: `PostgresConnector.introspect_schema()` (`apps/dla/src/dla/connectors/postgres.py`) calls `MetaData.reflect(schema=s)` per schema with default `resolve_fks=True`, which pulls cross-schema FK **targets** (and their FK closure) into the wrong schema pass — hr.employees(+departments/positions/locations) duplicated via finance, sales.dim_customers via analytics (= exactly +5/+30/+4/+1). The writer dedupes by path so disk is right, but downstream L2 consumers read the manifest. Repro: discover with the large config; compare `bundle.json.artifact_counts` to `ls schema/tables | wc -l`. Fix: `resolve_fks=False` or filter `metadata.tables` by `sa_table.schema == schema`.
- **D1b. `bundle validate` does not check manifest↔disk consistency**, so D1 ships silently even under `--strict`.
- **D2. jsonb / array columns cannot be profiled**: 6/673 columns fail with `TypeError: unhashable type: 'dict'|'list'` (distinct/top-value counting hashes raw values) — and profile_status `error` generates **no readiness issue**, so the failure is invisible in the report. Repro: profile the large config; see `bundle_large/profiles/analytics.typed_showcase.payload.json`.
- **D3. `dla run` cannot be aborted with Ctrl-C**: SIGINT mid-profile is swallowed and the pipeline runs to completion (verified twice; SIGTERM works). Operator-facing hazard on long engagements.

**P2 — behavior contradicts docs or produces wrong signals**
- **D4. Recommender scoring makes knowledge_graph structurally unable to beat vector** (both cap at 6; ties break to vector), and rel_density (rels ÷ **all** tables) is diluted by distractor/no-FK tables. 11-junction schema → vector. Consider density over connected tables, or weighting junction count above text saturation, or a higher KG cap.
- **D5. broken_fk check compares sampled values without type coercion** → varchar/int joins report 100% orphans (false Critical). `apps/dla/src/dla/readiness/checks.py::check_broken_fk`.
- **D6. Unset password env var exits 2 with a raw SQLAlchemy stack tail**, but README §Secrets promises the loader "fails fast with exit code 3 if a required variable is unset". The loader accepts the missing var and the connector attempts an empty password.
- **D7. `profile --table <nonexistent>` exits 0, "profiles: 0"** — silent no-op; exit-code table says 4 (resource not found). `describe` gets this right.
- **D8. Reconciliation never produces `conflict` for type mismatches from a CSV dictionary**: documented `money` vs discovered `numeric(10,2)` classified `match (exact, 100.0)`. README/M5 promises "conflict (they disagree, e.g. a type mismatch)".

**P3 — quality / robustness**
- **D9. Relationship inference singularization only strips a trailing 's'**: `stg_category_id → stg_categories` missed (`categorie_id` ≠ `category_id`); `customer_id → stg_customers` missed (prefix). -ies plurals are common; cheap fix.
- **D10. Value-overlap on serial ids is weak evidence**: distractor `analytics.stores (id 1..20)` attracted two **Strong (name+type+value_overlap)** cross-schema false-positive joins from `staging.*.store_id (1..25)`. Overlap of dense small-int surrogate ranges shouldn't upgrade confidence.
- **D11. Zero value overlap does not demote**: `stg_returns.stg_order_id` (100% orphans) still tagged **Strong** from name+type. Failed overlap check should be negative evidence, not neutral.
- **D12. Pattern-detector shape heuristics misfire at the margins**: compact facts (`fact_inventory_snapshots`, `stg_inventory`) classified junction (≤2 non-FK columns); master-data `hr.employees` classified a star fact; inferred false-positive rels propagate into "stars" (`stg_web_events` with the distractor store "dimension"). Self-referencing FKs are dropped from the graph, so `dim_accounts` snowflakes are undetectable (by design, worth documenting).
- **D13. Multi-column FK is flattened into two independent single-column relationships** (ledger fiscal_year→…, fiscal_month→…) — compositeness is lost in the contract.
- **D14. Glossary term extraction has no stop-list**: top proposals on this source are `name`, `status`, `created`, `stg`, `dim`, `fact` — technical prefixes and generic column names would be drafted as business terms in live mode.
- **D15. Table-describe prompt renders all column bullets as one 12KB line** (Jinja whitespace handling in `table_v1.j2` rendering) and has **no cap on column count** — 110 cols ≈ 3.3k tokens is fine, but a 1,000-column warehouse table would blow the prompt up ~10×.
- **D16. `bundle.json` is only maintained by discover**: `last_run_at` stays at discover time; profiles/readiness/patterns/kpi/recommendation counts never enter `artifact_counts`.
- **D17. Empty coverage reads as 100%**: `coverage_pct=1.0` when no reviewable artifacts exist, so FR-023's low-coverage confidence reduction can never trigger on a fresh bundle.
- **D18. Head-biased sampling**: profile samples are the first N rows (`events_tall` top values 1,2,3…), so stats on time-ordered tables reflect the oldest data.

## 7. What worked well (verified positives)

- **Idempotency is real**: 7 commands re-run over a 3,350-file bundle → zero diffs, zero mtime changes.
- Readiness caught **every** seeded issue class, including orphans behind a declared `NOT VALID` FK, with correct severities and useful `details`/suggestions.
- Reserved-word, quoted mixed-case, and 60-char identifiers survive the entire pipeline (discover→profile→describe→import→reconcile) with correct quoting.
- Exotic scalar types (uuid, enum, interval, bytea, inet, daterange) profile cleanly; the 110-column wide table and 100k-row tall table pose no functional problem; sample budget respected exactly.
- All 9 true junctions, both snowflake chains, and every real fact found by the detectors; staging contributed 0 declared / 9 inferred rels exactly as designed.
- `run`/`--resume`/exit-6, `--strict` exit-5, KPI ghost-table rejection exit-4, describe not-found exit-4 all match the documented contract.
- Recommender is deterministic and self-explaining; override flow works.
- Cross-schema FK, composite PKs, multi-col FK (modulo D13), self-referencing FKs all discovered.

## 8. Ranked fix list

1. D1 + D1b — manifest overcount + validate blind spot (contract-breaking for L2).
2. D2 — jsonb/array profiling failure + invisible `error` profiles (common column types).
3. D4 — recommender tie-break/density scaling (wrong hand-off signal at scale).
4. D5 — broken_fk type coercion (false Criticals erode trust in the report).
5. D3 — SIGINT handling in `dla run`.
6. D6/D7 — exit-code contract deviations (missing env var; silent no-op table filter).
7. D8 — unreachable conflict bucket for dictionary type mismatches.
8. D9/D10/D11 — inference naming + overlap-evidence improvements.
9. D14/D15 — glossary stop-list; prompt column-list newline + cap.
10. D16/D17/D18 — manifest freshness, empty-coverage semantics, sampling bias note.

## 9. Artifacts

- Fixture: `apps/dla/tests/fixtures/postgres_large/` (committed)
- Configs: `apps/dla/config/examples/postgres_large.yaml`, `postgres_large_staging_only.yaml` (committed)
- Bundles produced during the run (worktree-local, not committed): `bundle_large/`, `bundle_run/`, `bundle_resume*/`, `bundle_staging/`
- Raw logs: this scratchpad directory (`t1…t25`, `i1…i7`, `idem_*`, `e1…e3`)
