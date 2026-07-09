"""Bundle directory layout helpers.

The on-disk layout is the published contract (`docs/bundle-contract.md`); this
module is the single place path construction is centralized so the layout is
not duplicated across writer/reader/discovery/etc.
"""

from __future__ import annotations

from pathlib import Path

from dla.bundle.schema import ArtifactType

# Directory names relative to the bundle root.
_DIRECTORY_FOR_TYPE: dict[ArtifactType, tuple[str, ...]] = {
    ArtifactType.SOURCE: (),  # written directly under bundle root
    ArtifactType.TABLE: ("schema", "tables"),
    ArtifactType.COLUMN: ("schema", "columns"),
    ArtifactType.RELATIONSHIP: ("schema", "relationships"),
    ArtifactType.INDEX: ("schema", "indexes"),
    ArtifactType.PROFILE: ("profiles",),
    ArtifactType.READINESS_ISSUE: ("readiness", "issues"),
    ArtifactType.DESCRIPTION: ("descriptions",),  # tables/ or columns/ suffix decided by description target
    ArtifactType.GLOSSARY_ENTRY: ("glossary",),
    ArtifactType.PATTERN: ("patterns",),
    ArtifactType.KPI: ("kpi",),
    ArtifactType.HIERARCHY: ("hierarchies",),
    ArtifactType.IMPORTED_ARTIFACT: ("imports", "artifacts"),
    ArtifactType.RECONCILIATION_RESULT: ("imports", "reconciliation"),
    ArtifactType.TERM_MAPPING_RULE: ("term_mappings",),
    ArtifactType.RECOMMENDATION: ("recommendation",),
    ArtifactType.COVERAGE_RECORD: ("coverage",),
}


MANIFEST_FILENAME = "bundle.json"
DROPPED_DIRNAME = "_dropped"


def directory_for(bundle_root: Path, artifact_type: ArtifactType) -> Path:
    """Return the directory (under `bundle_root`) for a given artifact type."""
    parts = _DIRECTORY_FOR_TYPE[artifact_type]
    return bundle_root.joinpath(*parts) if parts else bundle_root


def filename_stem_for_artifact_id(artifact_id: str) -> str:
    """Convert an `artifact_id` to a safe filename stem.

    The `artifact_id` format is `<type>:<rest>` where `<rest>` may itself contain
    one or more `:` separators (e.g. `column:public.orders:status`). On disk the
    type prefix is dropped (the directory already encodes the type) and remaining
    `:` separators become `.` so the stem reads as a qualified name.

    Examples:
        `table:public.orders` -> `public.orders`
        `column:public.orders:status` -> `public.orders.status`
        `index:public.orders:idx_status` -> `public.orders.idx_status`
    """
    if ":" not in artifact_id:
        return artifact_id
    _type, _, rest = artifact_id.partition(":")
    return rest.replace(":", ".")


def paths_for(bundle_root: Path, artifact_id: str, artifact_type: ArtifactType) -> tuple[Path, Path]:
    """Return `(md_path, json_path)` for an artifact.

    The Source artifact is special-cased to `bundle_root/source.{md,json}`.
    """
    if artifact_type is ArtifactType.SOURCE:
        return bundle_root / "source.md", bundle_root / "source.json"
    stem = filename_stem_for_artifact_id(artifact_id)
    directory = directory_for(bundle_root, artifact_type)
    return directory / f"{stem}.md", directory / f"{stem}.json"


def manifest_path(bundle_root: Path) -> Path:
    return bundle_root / MANIFEST_FILENAME


def ensure_layout(bundle_root: Path) -> None:
    """Create all standard subdirectories under `bundle_root`.

    Called by the writer on first write so an empty bundle directory becomes a
    fully-laid-out one. Idempotent.
    """
    bundle_root.mkdir(parents=True, exist_ok=True)
    for parts in _DIRECTORY_FOR_TYPE.values():
        if parts:
            bundle_root.joinpath(*parts).mkdir(parents=True, exist_ok=True)
