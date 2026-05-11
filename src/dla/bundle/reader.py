"""Bundle reader — load existing artifacts back as typed pydantic models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dla.bundle.layout import directory_for, manifest_path
from dla.bundle.schema import (
    ArtifactType,
    BundleManifest,
    ColumnPayload,
    CommonFields,
    IndexPayload,
    ProfilePayload,
    ReadinessIssuePayload,
    RelationshipPayload,
    SourcePayload,
    TablePayload,
)

_MODEL_FOR_TYPE: dict[ArtifactType, type[CommonFields]] = {
    ArtifactType.SOURCE: SourcePayload,
    ArtifactType.TABLE: TablePayload,
    ArtifactType.COLUMN: ColumnPayload,
    ArtifactType.RELATIONSHIP: RelationshipPayload,
    ArtifactType.INDEX: IndexPayload,
    ArtifactType.PROFILE: ProfilePayload,
    ArtifactType.READINESS_ISSUE: ReadinessIssuePayload,
}


def load_manifest(bundle_root: Path) -> BundleManifest | None:
    p = manifest_path(bundle_root)
    if not p.exists():
        return None
    return BundleManifest.model_validate_json(p.read_text())


def load_json_artifact(json_path: Path) -> CommonFields:
    """Load one JSON artifact and return the strongly-typed payload."""
    raw: dict[str, Any] = json.loads(json_path.read_text())
    artifact_type = ArtifactType(raw["artifact_type"])
    model = _MODEL_FOR_TYPE.get(artifact_type)
    if model is None:
        raise NotImplementedError(
            f"Reader for artifact_type={artifact_type!r} not implemented yet "
            f"(scheduled for later milestone)."
        )
    return model.model_validate(raw)


def iter_artifacts(bundle_root: Path, artifact_type: ArtifactType) -> list[CommonFields]:
    """Return all artifacts of a given type currently on disk."""
    if artifact_type is ArtifactType.SOURCE:
        target = bundle_root / "source.json"
        return [load_json_artifact(target)] if target.exists() else []
    directory = directory_for(bundle_root, artifact_type)
    if not directory.exists():
        return []
    return [load_json_artifact(p) for p in sorted(directory.glob("*.json"))]
