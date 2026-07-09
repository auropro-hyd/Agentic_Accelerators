"""KPI validation (T145): source-table references must exist in the bundle,
and dimensions must resolve to discovered columns."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType, ColumnPayload


class KpiValidationError(ValueError):
    """Raised when a KPI references tables that aren't in the bundle."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__("source table(s) not found in bundle: " + ", ".join(missing))


class DimensionValidationError(ValueError):
    """Raised when a KPI dimension cannot be resolved to a discovered column."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("dimension(s) did not resolve: " + "; ".join(problems))


def normalize_table_ref(ref: str) -> str:
    """Accept `public.orders` or `table:public.orders`; return the artifact_id form."""
    ref = ref.strip()
    return ref if ref.startswith("table:") else f"table:{ref}"


def validate_source_tables(bundle_root: Path, source_table_refs: list[str]) -> None:
    """Raise KpiValidationError listing any source-table refs missing from the bundle."""
    existing = {t.artifact_id for t in iter_artifacts(bundle_root, ArtifactType.TABLE)}
    missing = [r for r in source_table_refs if r not in existing]
    if missing:
        raise KpiValidationError(missing)


def resolve_dimensions(
    bundle_root: Path,
    dimensions: list[str],
    source_table_refs: list[str],
) -> list[str]:
    """Resolve each dimension label to a `column:` artifact id.

    Accepted forms per dimension:
      - full artifact id:  `column:public.customers:region`
      - dotted path:       `public.customers.region` (schema.table.column)
      - bare column name:  `region` — matched against the columns of the KPI's
        source tables only; must match exactly one.

    Returns the resolved refs in input order. Raises DimensionValidationError
    listing every dimension that is missing or ambiguous (all problems are
    collected so the SME fixes them in one pass).
    """
    columns = cast(list[ColumnPayload], iter_artifacts(bundle_root, ArtifactType.COLUMN))
    by_id = {c.artifact_id for c in columns}
    source_tables = set(source_table_refs)

    resolved: list[str] = []
    problems: list[str] = []
    for dim in dimensions:
        label = dim.strip()
        if label.startswith("column:"):
            if label in by_id:
                resolved.append(label)
            else:
                problems.append(f"{label!r}: no such column in bundle")
            continue
        if "." in label:
            # `schema.table.column` — the last dot separates the column name.
            table_part, _, column_part = label.rpartition(".")
            candidate = f"column:{table_part}:{column_part}"
            if candidate in by_id:
                resolved.append(candidate)
            else:
                problems.append(f"{label!r}: no such column in bundle")
            continue
        matches = [
            c.artifact_id
            for c in columns
            if c.name == label and c.table_ref in source_tables
        ]
        if len(matches) == 1:
            resolved.append(matches[0])
        elif not matches:
            problems.append(
                f"{label!r}: not found in the KPI's source tables "
                f"(use schema.table.column to point elsewhere)"
            )
        else:
            problems.append(f"{label!r}: ambiguous — candidates: {', '.join(sorted(matches))}")
    if problems:
        raise DimensionValidationError(problems)
    return resolved
