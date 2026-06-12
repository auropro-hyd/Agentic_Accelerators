"""dbt `manifest.json` importer (T106).

SECURITY (T124): the manifest is read as **plain JSON** — `json.loads` only.
No Jinja rendering, no dbt runtime, no code evaluation of any kind. A
description containing `{{ exec(...) }}` is treated as an inert string.

Extracts model-node descriptions (→ table descriptions) and their column
descriptions (→ column descriptions). Non-model nodes (seeds, tests, sources)
are ignored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dla.bundle.schema import ArtifactType, SourceFormat
from dla.importers import RawImport


def import_manifest(path: Path) -> tuple[list[RawImport], list[str]]:
    """Return (records, skip_reasons) for one dbt manifest.json."""
    try:
        manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [], [f"{path.name}: unreadable manifest ({exc})"]

    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        return [], [f"{path.name}: manifest has no `nodes` object"]

    records: list[RawImport] = []
    skips: list[str] = []
    for node_id, node in nodes.items():
        if not isinstance(node, dict) or node.get("resource_type") != "model":
            continue
        schema = str(node.get("schema") or "").strip()
        name = str(node.get("name") or "").strip()
        if not schema or not name:
            skips.append(f"{node_id}: model missing schema/name")
            continue
        table_key = f"{schema}.{name}"

        table_desc = str(node.get("description") or "").strip()
        if table_desc:
            records.append(
                RawImport(
                    source_format=SourceFormat.DBT_MANIFEST,
                    source_path=str(path),
                    target_artifact_type=ArtifactType.DESCRIPTION,
                    target_ref=f"table:{table_key}",
                    proposed_value=table_desc,
                    raw_payload={"node_id": node_id, "kind": "table"},
                )
            )
        columns = node.get("columns")
        if isinstance(columns, dict):
            for col_name, col in columns.items():
                if not isinstance(col, dict):
                    continue
                col_desc = str(col.get("description") or "").strip()
                if not col_desc:
                    continue
                records.append(
                    RawImport(
                        source_format=SourceFormat.DBT_MANIFEST,
                        source_path=str(path),
                        target_artifact_type=ArtifactType.DESCRIPTION,
                        target_ref=f"column:{table_key}:{col_name}",
                        proposed_value=col_desc,
                        raw_payload={"node_id": node_id, "kind": "column", "column": col_name},
                    )
                )
    return records, skips
