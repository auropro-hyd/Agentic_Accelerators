"""CSV / Excel data-dictionary importer (T104).

Expects a tabular file with (at least) `table`, `column`, `description`
columns; an optional `data_type` column is carried into `raw_payload` for the
reconciliation type-conflict check. Malformed rows are skipped, not fatal.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dla.bundle.schema import ArtifactType, SourceFormat
from dla.importers import RawImport

_REQUIRED = ("table", "column", "description")


def import_dictionary(path: Path) -> tuple[list[RawImport], list[str]]:
    """Return (records, skip_reasons) for one CSV/XLSX dictionary file."""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        fmt = SourceFormat.EXCEL_DICTIONARY
        frame = pd.read_excel(path, dtype=str)
    else:
        fmt = SourceFormat.CSV_DICTIONARY
        frame = pd.read_csv(path, dtype=str)

    frame = frame.rename(columns={c: str(c).strip().lower() for c in frame.columns})
    skips: list[str] = []
    missing = [c for c in _REQUIRED if c not in frame.columns]
    if missing:
        return [], [f"{path.name}: missing required column(s): {', '.join(missing)}"]

    records: list[RawImport] = []
    for idx, row in frame.iterrows():
        table = (row.get("table") or "").strip() if isinstance(row.get("table"), str) else ""
        column = (row.get("column") or "").strip() if isinstance(row.get("column"), str) else ""
        desc = row.get("description")
        desc = desc.strip() if isinstance(desc, str) else ""
        if not table or not column or not desc:
            skips.append(f"{path.name} row {idx}: blank table/column/description")
            continue
        payload = {k: (v if isinstance(v, str) else None) for k, v in row.to_dict().items()}
        records.append(
            RawImport(
                source_format=fmt,
                source_path=str(path),
                target_artifact_type=ArtifactType.DESCRIPTION,
                target_ref=f"column:{table}:{column}",
                proposed_value=desc,
                raw_payload=payload,
            )
        )
    return records, skips
