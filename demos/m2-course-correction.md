# M2 Course-Correction Questions

**Date:** 2026-05-15 (target)
**Asked of:** Akhilesh
**Default rule:** if no response within 48 hours, we continue with the
implementer's preferred answer and revisit at the M3 demo.

---

## Q1. Severity thresholds

Current thresholds (in `config/default.yaml`, overridable per-engagement):

- `null_rate ≥ 0.5` → `high_null_rate` issue at `warning` severity
- `null_rate ≥ 0.9` → escalate to `critical`
- `null_rate = 1.0` → reclassified as `all_null_column` (always `critical`)

Are these the right bands?

- *Implementer preference: yes.* Real engagements have shown 50% nulls is
  usually a real concern; 90%+ is almost always a data-quality bug or an
  unused column.

## Q2. `unprofiled` severity

A column that couldn't be profiled (permission denied, type unsupported,
etc.) currently lands at `info`. M3 description generation can't ground
on an unprofiled column. Should `unprofiled` escalate to `critical`?

- *Implementer preference: keep `info` but introduce a derived issue
  "no description generated due to unprofiled column" in M3 at `warning`
  severity.* That keeps the unprofiled signal separate from its
  downstream effect.

## Q3. Profile sample sizes

Default `sample_budget_rows = 10_000`. For columns with 100K+ rows,
that's a 10% sample; for very wide columns it's enough for stable null
rate but the `top_values` may miss long-tail values.

Two adjustable axes:
- raise the default to 50k?
- or stay at 10k but encourage `--mode full_scan` for opt-in completeness?

- *Implementer preference: stay at 10k default.* 50k slows demos and
  M1→M3 iteration; full_scan exists for SMEs who need exact answers.

## Q4. `constant_column` minimum sample size

Today's demo flagged 39 `constant_column` issues, but most are 1-3-row
fixture tables where distinct=1 is arithmetically inevitable. Should we
require `sample_size >= N` before flagging?

- *Implementer preference: require `sample_size >= 50` before flagging
  `constant_column`.* Cuts the noise without losing any real signal.
  Trivial change to `readiness/checks.py`.

## Q5. Pre-M3 polish

If we have buffer between today's demo and M3 starting Monday, where
should it go?
- A. More integration tests (testcontainers Postgres)
- B. Snowflake connector (pull forward from M8)
- C. Demo-friendly readiness summary HTML
- D. None — straight to M3

- *Implementer preference: A.* Integration coverage on Postgres is the
  unstable spot before AI features land.

---

## How to respond

Reply to my Teams message with **accept all** or per-question.
