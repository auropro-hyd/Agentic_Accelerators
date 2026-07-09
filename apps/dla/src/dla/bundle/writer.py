"""Atomic bundle writer.

Writes paired markdown + JSON files for every artifact, using
write-to-temp + fsync + atomic-rename so partial writes are never observed.

Two correctness guarantees enforced here:

1. **SME preservation (FR-012)**: artifacts whose existing provenance is
   `ai-drafted-edited`, `sme-authored`, or `client-provided-reconciled` are
   never clobbered by a re-run unless `force=True`.
2. **Idempotent re-run (M1 DoD)**: when the new payload's content is
   byte-identical to what's on disk modulo timestamps, the file is left alone
   (preserving both `created_at` and `updated_at`). When the content differs,
   `created_at` is preserved from the existing file and `updated_at` is set
   from the new payload.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter
from pydantic import BaseModel

from dla.bundle.layout import (
    count_artifacts_on_disk,
    ensure_layout,
    manifest_path,
    paths_for,
)
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
    already_current: bool = False
    """True when on-disk content (modulo timestamps) matched the new payload
    and no write was needed."""


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
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


# Fields that legitimately change on every run and must be excluded when
# comparing new vs existing content to decide whether a write is necessary.
_TIMESTAMP_FIELDS = ("created_at", "updated_at", "discovered_at")


def _data_to_json_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, default=str) + "\n").encode("utf-8")


def _data_to_markdown_bytes(
    data: dict[str, Any], body: str, *, md_exclude_keys: set[str] | None = None
) -> bytes:
    """Render `data` as YAML frontmatter + `body` as markdown body.

    `md_exclude_keys` lets the caller keep a field in the JSON sibling but
    out of the YAML frontmatter — used for description artifacts where the
    prose body is the canonical text and replicating it in YAML both
    duplicates content and exposes the YAML parser to user-text edge cases
    (colons, multiline blocks, etc.).
    """
    md_data = (
        {k: v for k, v in data.items() if k not in md_exclude_keys}
        if md_exclude_keys
        else data
    )
    post = frontmatter.Post(content=body, **md_data)
    return frontmatter.dumps(post, sort_keys=False).encode("utf-8") + b"\n"


def _read_existing_json(json_path: Path) -> dict[str, Any] | None:
    if not json_path.exists():
        return None
    try:
        result = json.loads(json_path.read_text())
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _existing_provenance(data: dict[str, Any] | None) -> Provenance | None:
    if data is None:
        return None
    raw = data.get("provenance")
    if raw is None:
        return None
    try:
        return Provenance(raw)
    except ValueError:
        return None


def _strip_for_comparison(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in _TIMESTAMP_FIELDS}


def write_artifact(
    bundle_root: Path,
    payload: CommonFields,
    *,
    body: str = "",
    force: bool = False,
    md_exclude_keys: set[str] | None = None,
) -> WriteResult:
    """Write one artifact (paired `.md` + `.json`) to the bundle.

    - Creates the bundle layout if missing (idempotent).
    - Refuses to clobber SME-edited or SME-authored artifacts unless `force=True`.
      (FR-012). When skipped, returns `skipped_to_preserve_sme=True`.
    - Enforces the provenance state machine on any transition.
    - When the new payload is content-identical (modulo timestamps) to what's
      already on disk, leaves both files alone — that guarantees re-run idempotency.
    - When content differs, preserves the existing `created_at` and writes
      the new payload's `updated_at`.
    """
    ensure_layout(bundle_root)
    md_path, json_path = paths_for(
        bundle_root, payload.artifact_id, ArtifactType(payload.artifact_type)
    )

    existing_data = _read_existing_json(json_path)
    existing_state = _existing_provenance(existing_data)

    if existing_state is not None and preserves_sme_work(existing_state) and not force:
        return WriteResult(
            artifact_id=payload.artifact_id,
            md_path=str(md_path),
            json_path=str(json_path),
            skipped_to_preserve_sme=True,
        )

    assert_transition_allowed(existing_state, payload.provenance)

    # Serialize the new payload through pydantic's JSON encoder once, then
    # work in dict form so we can preserve / merge timestamps cleanly.
    new_data: dict[str, Any] = json.loads(payload.model_dump_json())

    if existing_data is not None:
        if "created_at" in existing_data:
            new_data["created_at"] = existing_data["created_at"]
        if _strip_for_comparison(new_data) == _strip_for_comparison(existing_data):
            # Idempotent: do not touch the files.
            return WriteResult(
                artifact_id=payload.artifact_id,
                md_path=str(md_path),
                json_path=str(json_path),
                already_current=True,
            )

    json_bytes = _data_to_json_bytes(new_data)
    md_bytes = _data_to_markdown_bytes(new_data, body=body, md_exclude_keys=md_exclude_keys)

    # Write JSON first so a partial state never has md-without-json.
    _atomic_write(json_path, json_bytes)
    try:
        _atomic_write(md_path, md_bytes)
    except Exception:
        # Roll back the json write — the artifact pair must be all-or-nothing.
        with contextlib.suppress(FileNotFoundError):
            json_path.unlink()
        raise

    return WriteResult(
        artifact_id=payload.artifact_id,
        md_path=str(md_path),
        json_path=str(json_path),
    )


_MANIFEST_TIMESTAMP_FIELDS = ("last_run_at",)


def write_manifest(bundle_root: Path, manifest: BundleManifest) -> Path:
    """Write `bundle/bundle.json`.

    Idempotent: if the manifest's content (modulo `last_run_at`) matches what's
    already on disk, leaves the file alone so re-runs produce zero diffs.
    """
    path = manifest_path(bundle_root)
    new_data: dict[str, Any] = json.loads(manifest.model_dump_json())

    existing = _read_existing_json(path)
    if existing is not None:
        new_strip = {k: v for k, v in new_data.items() if k not in _MANIFEST_TIMESTAMP_FIELDS}
        old_strip = {k: v for k, v in existing.items() if k not in _MANIFEST_TIMESTAMP_FIELDS}
        if new_strip == old_strip:
            return path  # no-op
        # Preserve a stable last_run_at when the rest matches? No — last_run_at
        # genuinely represents the latest run; we only suppress writes when the
        # whole content matches, which it does not here.

    _atomic_write(path, _data_to_json_bytes(new_data))
    return path


def refresh_manifest_counts(
    bundle_root: Path, *, source_id: str | None = None
) -> BundleManifest | None:
    """Recount every artifact type from disk and refresh `bundle.json` (D16).

    Called by every writing command (discover, profile, readiness, describe,
    glossary, patterns, kpi, hierarchy, import, reconcile, recommend) so the
    manifest's `artifact_counts` always reflects what is actually on disk —
    not just what the last `discover` wrote.

    Idempotency-preserving by construction: the manifest file is rewritten
    (and `last_run_at` moves) **only when the recounted `artifact_counts`
    differ** from what the manifest already says — `write_manifest` no-ops
    when the content modulo `last_run_at` is unchanged. Re-running a command
    over an unchanged bundle therefore produces zero diffs, not even mtimes.

    When no manifest exists yet, one is seeded — but only if the caller can
    supply a `source_id` (otherwise this is a no-op returning None).
    """
    manifest: BundleManifest | None = None
    existing = _read_existing_json(manifest_path(bundle_root))
    if existing is not None:
        try:
            manifest = BundleManifest.model_validate(existing)
        except Exception:
            manifest = None  # corrupt manifest — rebuild below if we can
    if manifest is None:
        if source_id is None:
            return None
        manifest = BundleManifest(
            source_id=source_id,
            last_run_at=now_utc(),
            bundle_root=str(bundle_root),
        )
    manifest.artifact_counts = count_artifacts_on_disk(bundle_root)
    manifest.last_run_at = now_utc()
    write_manifest(bundle_root, manifest)
    return manifest


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
    "refresh_manifest_counts",
    "update_artifact_counts",
    "write_artifact",
    "write_manifest",
]
