"""Structured markdown notes importer (T105).

Each `.md` note carries YAML frontmatter naming its target, and a body that is
the proposed description:

    ---
    target: public.customers.full_name
    target_kind: column          # column | table  (default: column)
    ---
    Full legal name of the customer ...

`--client-docs <path>` may point at a single `.md` file or a folder of them.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter

from dla.bundle.schema import ArtifactType, SourceFormat
from dla.importers import RawImport


def _target_ref(target: str, kind: str) -> str | None:
    target = target.strip()
    if not target:
        return None
    if ":" in target:  # already an artifact_id
        return target
    if kind == "table":
        return f"table:{target}"
    # column: last dotted segment is the column, the rest is the table
    table, _, column = target.rpartition(".")
    if not table or not column:
        return None
    return f"column:{table}:{column}"


def _import_file(path: Path) -> tuple[list[RawImport], list[str]]:
    try:
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], [f"{path.name}: unreadable markdown ({exc})"]
    target = str(post.get("target", "")).strip()
    kind = str(post.get("target_kind", "column")).strip() or "column"
    body = str(post.content).strip()
    ref = _target_ref(target, kind)
    if ref is None or not body:
        return [], [f"{path.name}: missing frontmatter `target` or empty body"]
    return [
        RawImport(
            source_format=SourceFormat.MARKDOWN_NOTES,
            source_path=str(path),
            target_artifact_type=ArtifactType.DESCRIPTION,
            target_ref=ref,
            proposed_value=body,
            raw_payload={"target": target, "target_kind": kind},
        )
    ], []


def import_notes(path: Path) -> tuple[list[RawImport], list[str]]:
    """Return (records, skip_reasons) for one `.md` file or a folder of them."""
    files = sorted(path.glob("*.md")) if path.is_dir() else [path]
    records: list[RawImport] = []
    skips: list[str] = []
    for f in files:
        recs, sk = _import_file(f)
        records.extend(recs)
        skips.extend(sk)
    return records, skips
