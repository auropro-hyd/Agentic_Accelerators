# M1 Course-Correction Questions

**Date:** 2026-05-11
**Asked of:** Akhilesh
**Default rule:** if no response within 48 hours, we continue with the
implementer's preferred answer (noted in italics) and revisit at the M2
demo.

---

## Q1. Bundle directory layout

Does the bundle/ layout shown in M1's demo feel right for downstream
consumers (RAG agents, eval harnesses, SME web UI), or should we
restructure before M2 piles more artifact types in?

- *Implementer preference: keep as-is.* The schema/{tables,columns,
  relationships,indexes} split mirrors the connector's view; downstream
  consumers are typed-by-artifact_type, not path-driven; further splits
  (profiles/, readiness/, descriptions/) are additive.

## Q2. Confidence labels

`Explicit` / `Strong` / `Weak` plus a signals array — or would you prefer
a numeric 0–1 score (e.g., `confidence: 0.83`)?

- *Implementer preference: keep the 3-value enum.* Numeric scores invite
  spurious precision; SMEs deal with three labels naturally. The signals
  array (e.g., `[name_match, type_match, value_overlap]`) gives the
  underlying reason in case the label is questioned.

## Q3. Snowflake — keep for M8, or pull forward?

The plan has Snowflake landing in M8 (after the SME UI and import work).
If your first real engagement is Snowflake-shaped, pulling it forward to
right after M2 would mean we're not blocked at M8. Pulling forward costs
~3 days of M5/M6 displacement.

- *Implementer preference: keep for M8 unless you have a specific
  Snowflake engagement queued.* The connector is mechanically simple
  (SQLAlchemy reflection over snowflake-sqlalchemy); the real M2-M7 risk
  is in profiling, AI descriptions, and SME UX, which is provider-agnostic.

## Q4. Sixth provenance value (`discovered`)

`data-model.md` lists 5 provenance values
(`client-provided` / `client-provided-reconciled` / `ai-drafted` /
`ai-drafted-edited` / `sme-authored`). None of those fit factual schema
artifacts (tables, columns, relationships, indexes) — they aren't AI
drafts and they aren't SME work, they're just discovered facts. M1 added
a sixth value, `discovered`, to cover them.

- *Implementer preference: keep `discovered` as the canonical sixth
  value.* Alternative names considered: `factual`, `connector`. None
  improved clarity.

---

## How to respond

Reply to my Teams message with one of: **accept all** / **accept Qn / Qm**
/ **comments** (in which case we'll talk).
