# DLA Operator Guide

This guide is for operators running a Data Layer Accelerator (`dla`) engagement:
turning a client data source into a validated **bundle** and a strategy
**recommendation** that hand off to the layers above L1. It covers install, the
one-command pipeline, every step, how to resume a run, exit codes, and
validation/hand-off.

For the shape of what the pipeline produces, see
[`bundle-contract.md`](bundle-contract.md).

---

## 1. Prerequisites & install

`dla` lives in a [`uv`](https://docs.astral.sh/uv/) workspace alongside the
shared `libs/core` and `libs/llm` packages.

```bash
uv sync            # install the workspace (creates .venv, installs all packages)
```

**Local development** — if you run modules without installing the workspace
into the environment, put the source roots on `PYTHONPATH`:

```bash
export PYTHONPATH=libs/core/src:libs/llm/src:apps/dla/src
```

**Environment variables**

| Variable | When needed | Purpose |
|----------|-------------|---------|
| `DLA_DB_PASSWORD` | Postgres sources | Password for the source database connection. Kept out of the YAML config. |
| `AZURE_OPENAI_KEY` (or the configured LLM provider key) | `--llm` runs only | Credential for the LLM gateway used by the `describe` and `glossary` steps. |
| `DLA_SME_NAME` | SME edits / overrides | Identifies the subject-matter expert authoring or overriding artifacts, recorded as provenance. |

Offline steps (everything except `describe` and `glossary`) do not need an LLM
key, so a run without `--llm` can proceed with no LLM credential set.

---

## 2. The one-command pipeline

A single command takes a source through to a validated bundle:

```bash
dla run -c <config.yaml>            # offline: discover .. recommend .. validate
dla run -c <config.yaml> --llm      # also drafts descriptions + glossary
```

- **Without `--llm`** the pipeline runs fully offline. The two LLM-gated steps
  (`describe`, `glossary`) are **skipped**, and the run reports them as skipped.
  This is the mode used in CI and tests.
- **With `--llm`** the gateway is built from the config's `llm` section and the
  `describe` and `glossary` steps also run, drafting prose descriptions and
  business-term definitions.

The bundle directory comes from `--bundle-dir`, else the config's
`runtime.bundle_dir`.

> Note: `import` and `reconcile` are driven by explicit client-document paths,
> not the engagement config, so `dla run` does not perform them.

---

## 3. Pipeline steps

The full ordered pipeline (`STEP_ORDER`) is:

| # | Step | LLM? | Produces |
|---|------|------|----------|
| 1 | `discover` | no | Schema artifacts under `schema/` — tables, columns, relationships, indexes — from the connected source. |
| 2 | `profile` | no | Per-column profiles under `profiles/` (nulls, distinct, samples, quantiles), by sampling. |
| 3 | `readiness` | no | Readiness report `readiness/readiness.md` plus one file per data-quality issue under `readiness/issues/`. |
| 4 | `describe` | **yes** | AI-drafted table/column prose under `descriptions/`. Skipped when `--llm` is not set. |
| 5 | `glossary` | **yes** | Recurring business terms under `glossary/`, extracted then defined. Skipped when `--llm` is not set. |
| 6 | `patterns` | no | Detected schema shapes (star/snowflake/junction/audit) under `patterns/`. |
| 7 | `recommend` | no | The deterministic strategy recommendation under `recommendation/` (`plain_schema` / `vector` / `knowledge_graph`). |
| 8 | `validate` | no | Validates every artifact against the bundle contract; carries the error count into the run result. |

Progress is recorded to `bundle/.run_state.json` after each step so a later
resume can skip finished work.

---

## 4. Resumability matrix

**Every step is idempotent and safe to re-enter.** The bundle writers preserve
SME- and client-authored work and no-op on unchanged content, so re-running a
step never clobbers human work — this is what makes resumption correct.

| Step | Reads | Writes | Resume from it |
|------|-------|--------|----------------|
| `discover` | Source connector | `schema/` | `--from-step discover` |
| `profile` | Source connector, `schema/` | `profiles/` | `--from-step profile` |
| `readiness` | `schema/`, `profiles/` (connector) | `readiness/` | `--from-step readiness` |
| `describe` | `schema/`, `profiles/` (+ LLM) | `descriptions/` | `--from-step describe --llm` |
| `glossary` | Descriptions / bundle text (+ LLM) | `glossary/` | `--from-step glossary --llm` |
| `patterns` | `schema/`, relationships | `patterns/` | `--from-step patterns` |
| `recommend` | Whole bundle (signals) | `recommendation/` | `--from-step recommend` |
| `validate` | Whole bundle | (report only) | `--from-step validate` |

### Controlling the plan

- **`--from-step <step>`** — start at this step (inclusive) and run through the
  end, skipping everything before it. Takes precedence over `--resume`.
- **`--resume`** — start **after the last completed step** recorded in
  `bundle/.run_state.json`. If no state exists, runs the full pipeline.
- **`--skip-step <step>`** — drop a step from the plan entirely. Repeatable
  (pass it more than once for multiple steps).
- **`--stop-on-readiness-critical`** — during `readiness`, if any critical
  data-quality issue is found, halt the run before `describe` rather than
  drafting on top of bad data. Exits with code **7**.

An unknown step name for `--from-step` or `--skip-step` is a usage error
(exit code **3**).

---

## 5. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | Generic error. |
| 2 | Connection / source / LLM-provider transport failure. |
| 3 | Config or usage error. |
| 4 | Resource not found (artifact / path / table / column). |
| 5 | Validation failure (bundle-contract validation, or an unparseable LLM response). |
| 6 | User-cancelled / nothing to resume. |
| 7 | Halted by policy (readiness-critical stop via `--stop-on-readiness-critical`). |

---

## 6. Validation & hand-off

Validate the bundle against the contract at any time:

```bash
dla bundle validate -c <config.yaml>            # every artifact must round-trip its model
dla bundle validate -c <config.yaml> --strict   # warnings fail too
```

`validate` reports **errors** (malformed artifact, KPI referencing a missing
table, missing manifest) and **warnings** (undescribed table, no recommendation
yet). It is both a quality gate and a security gate — an artifact that does not
match the contract never ships. You can also point it at a bundle directly with
`--bundle-dir` instead of `-c`.

Publish or regenerate the machine-readable schema:

```bash
dla bundle export-schema                 # write config/schemas/bundle-schema.json
dla bundle export-schema --out <path>    # to a chosen path
```

**The hand-off to downstream layers** is: the **bundle** directory, the
generated **`bundle-schema.json`**, and the deterministic **recommendation**.
The recommended strategy routes the work — `knowledge_graph` to the
knowledge-graph accelerator, `vector` to the vector/semantic layer,
`plain_schema` to straight relational modeling.

---

## 7. Recovering from a failed run

When a step fails, the pipeline records the failure to `.run_state.json`, prints
the failing **step name**, and (for step failures) suggests a resume command.

1. **Read the error** — it names the step that failed (e.g. `pipeline failed at
   step 'profile'`).
2. **Fix the cause** — for example a bad credential (`DLA_DB_PASSWORD`,
   the LLM key), an unreachable source, or a config problem.
3. **Resume** — re-run from that step; everything before it is left intact:

   ```bash
   dla run -c <config.yaml> --from-step <step>
   ```

   Add `--llm` if the resumed range includes `describe` or `glossary`.

Because every step is idempotent, re-running a step (or the whole pipeline)
never damages already-good artifacts, so when in doubt you can safely re-run.
