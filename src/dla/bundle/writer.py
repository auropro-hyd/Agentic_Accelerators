"""Atomic bundle writer.

Writes paired markdown + JSON files for every artifact, using
write-to-temp + fsync + atomic-rename so partial writes are never observed.
Consults the provenance state machine before overwriting an existing artifact
(FR-012: re-runs preserve SME work).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter
from pydantic import BaseModel

from dla.bundle.layout import ensure_layout, manifest_path, paths_for
from dla.bundle.provenance import (
    Provenance,
    assert_transition_allowed,
    preserves_sme_work,
)
from dla.bundle.schema import ArtifactType, BundleManifest, CommonFields


class WriteResult(BaseModel):
    """Outcome of a single `write_artifact` call."""

    artifact_id: str
    md_path: str
    json_path: str
    skipped_to_preserve_sme: bool = False


def _atomic_write(target: Path, contents: bytes) -> None:
    """Write `contents` to `target` atomically (temp file + fsync + rename)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(contents)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception:
        # If anything goes wrong, drop the temp file.
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _payload_to_json_bytes(payload: CommonFields) -> bytes:
    return (payload.model_dump_json(indent=2, by_alias=False) + "\n").encode("utf-8")


def _payload_to_markdown_bytes(payload: CommonFields, body: str) -> bytes:
    metadata = json.loads(payload.model_dump_json(by_alias=False))
    post = frontmatter.Post(content=body, **metadata)
    return frontmatter.dumps(post, sort_keys=False).encode("utf-8") + b"\n"


def _read_existing_provenance(json_path: Path) -> Provenance | None:
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    raw = data.get("provenance")
    if raw is None:
        return None
    try:
        return Provenance(raw)
    except ValueError:
        return None


def write_artifact(
    bundle_root: Path,
    payload: CommonFields,
    *,
    body: str = "",
    force: bool = False,
) -> WriteResult:
    """Write one artifact (paired `.md` + `.json`) to the bundle.

    - Creates the bundle layout if missing (idempotent).
    - Refuses to clobber SME-edited or SME-authored artifacts unless `force=True`
      (FR-012 re-run preservation). When skipped, returns `skipped_to_preserve_sme=True`.
    - Otherwise enforces the provenance state machine for any transition.

    Both files are written atomically and either both succeed or neither
    becomes visible.
    """
    ensure_layout(bundle_root)
    md_path, json_path = paths_for(
        bundle_root, payload.artifact_id, ArtifactType(payload.artifact_type)
    )

    existing = _read_existing_provenance(json_path)
    if existing is not None and preserves_sme_work(existing) and not force:
        return WriteResult(
            artifact_id=payload.artifact_id,
            md_path=str(md_path),
            json_path=str(json_path),
            skipped_to_preserve_sme=True,
        )

    assert_transition_allowed(existing, payload.provenance)

    json_bytes = _payload_to_json_bytes(payload)
    md_bytes = _payload_to_markdown_bytes(payload, body=body)

    # Write JSON first so a partial state never has md-without-json.
    _atomic_write(json_path, json_bytes)
    try:
        _atomic_write(md_path, md_bytes)
    except Exception:
        # roll back the json write — the artifact pair must be all-or-nothing
        try:
            json_path.unlink()
        except FileNotFoundError:
            pass
        raise

    return WriteResult(
        artifact_id=payload.artifact_id,
        md_path=str(md_path),
        json_path=str(json_path),
    )


def write_manifest(bundle_root: Path, manifest: BundleManifest) -> Path:
    """Write `bundle/bundle.json`."""
    path = manifest_path(bundle_root)
    _atomic_write(
        path, (manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
    )
    return path


def now_utc() -> datetime:
    """Single source of `created_at`/`updated_at` values — easy to monkeypatch in tests."""
    return datetime.now(UTC)


def update_artifact_counts(manifest: BundleManifest, counts: dict[ArtifactType, int]) -> None:
    """In-place update of `manifest.artifact_counts` from typed counts."""
    out: dict[str, int] = {}
    for k, v in counts.items():
        key = k.value if isinstance(k, ArtifactType) else str(k)
        out[key] = v
    manifest.artifact_counts = out


__all__ = [
    "WriteResult",
    "now_utc",
    "update_artifact_counts",
    "write_artifact",
    "write_manifest",
]
