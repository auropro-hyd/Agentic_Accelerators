"""M8 T182/T183 — bundle-contract parity + schema-version pin.

Guards the published contract against silent drift (FR-024):
- the committed `bundle-schema.json` must equal what the models generate now;
- the manifest's `schema_version` must equal the published schema `version`;
- every persisted artifact type must have a payload in the schema (with the one
  documented exception, `coverage_record`, which is computed on demand — E13 —
  and never written to disk).
"""

from __future__ import annotations

from json import loads
from pathlib import Path

from dla.bundle.contract import DEFAULT_SCHEMA_PATH, build_schema
from dla.bundle.schema import SCHEMA_VERSION, ArtifactType, BundleManifest

# Artifact types intentionally absent from the persisted-payload schema.
_COMPUTED_ONLY = {ArtifactType.COVERAGE_RECORD}

_COMMITTED_SCHEMA = Path(__file__).parents[2] / "config" / "schemas" / "bundle-schema.json"


def test_schema_version_is_pinned() -> None:
    """T183: manifest schema_version == published schema version == constant."""
    assert BundleManifest.model_fields["schema_version"].default == SCHEMA_VERSION
    assert build_schema()["version"] == SCHEMA_VERSION


def test_committed_schema_matches_generated() -> None:
    """T182: the checked-in bundle-schema.json must not drift from the models.

    If this fails, run `dla bundle export-schema` and commit the result.
    """
    assert _COMMITTED_SCHEMA.exists(), (
        f"{_COMMITTED_SCHEMA} missing — run `dla bundle export-schema`. "
        f"(DEFAULT_SCHEMA_PATH={DEFAULT_SCHEMA_PATH})"
    )
    committed = loads(_COMMITTED_SCHEMA.read_text())
    assert committed == build_schema(), (
        "bundle-schema.json is stale — regenerate with `dla bundle export-schema`."
    )


def test_every_artifact_type_has_a_payload_or_is_computed() -> None:
    """Every ArtifactType is either in the schema's discriminator mapping or is
    a documented computed-only type."""
    mapping = build_schema().get("discriminator", {}).get("mapping", {})
    assert mapping, "discriminated union lost its mapping"
    covered = set(mapping.keys())
    for at in ArtifactType:
        if at in _COMPUTED_ONLY:
            assert at.value not in covered, (
                f"{at.value} is marked computed-only but appears in the persisted schema"
            )
        else:
            assert at.value in covered, f"artifact type {at.value} has no payload in the schema"
