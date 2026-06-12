"""M5 — CSV/markdown dictionary import + normalize (T104/T105/T107/T110)."""

from __future__ import annotations

from pathlib import Path

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType, ImportedArtifactPayload, SourceFormat
from dla.importers.csv_dictionary import import_dictionary
from dla.importers.markdown_notes import import_notes
from dla.importers.normalize import normalize_and_write

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "client_docs"


def test_csv_dictionary_parses_all_rows() -> None:
    records, skips = import_dictionary(_FIX / "data_dictionary.csv")
    assert skips == []
    assert len(records) == 4
    refs = {r.target_ref for r in records}
    assert "column:public.orders:status" in refs
    assert "column:public.orders:discount_pct" in refs  # the orphan-to-be
    assert all(r.source_format == SourceFormat.CSV_DICTIONARY for r in records)


def test_markdown_notes_parses_target() -> None:
    records, skips = import_notes(_FIX / "notes.md")
    assert skips == []
    assert len(records) == 1
    assert records[0].target_ref == "column:public.customers:full_name"
    assert "Full legal name" in records[0].proposed_value


def test_malformed_csv_is_skipped_not_fatal(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("table,column\npublic.orders,status\n")  # missing 'description'
    records, skips = import_dictionary(bad)
    assert records == []
    assert skips and "missing required column" in skips[0]


def test_normalize_writes_imported_artifacts_idempotently(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    records, _ = import_dictionary(_FIX / "data_dictionary.csv")
    report = normalize_and_write(bundle_root=bundle, raws=records, source_id="s")
    assert report.written == 4

    arts = iter_artifacts(bundle, ArtifactType.IMPORTED_ARTIFACT)
    assert len(arts) == 4
    assert all(isinstance(a, ImportedArtifactPayload) for a in arts)
    assert all(a.provenance == Provenance.CLIENT_PROVIDED for a in arts)

    # Re-import is idempotent: same artifacts, no duplicates.
    normalize_and_write(bundle_root=bundle, raws=records, source_id="s")
    assert len(iter_artifacts(bundle, ArtifactType.IMPORTED_ARTIFACT)) == 4
