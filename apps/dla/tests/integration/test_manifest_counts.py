"""D16 exit test — discover keeps the manifest's counts equal to disk, for all
artifact types, and a re-run over an unchanged source is a zero-diff no-op
(bytes AND mtimes), including `bundle.json` itself."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dla.bundle.layout import count_artifacts_on_disk
from dla.bundle.reader import load_manifest
from dla.bundle.schema import ArtifactType
from dla.config.models import Config, CsvFolderConnectionConfig, SourceConfig
from dla.connectors.csv_folder import build as build_csv_folder
from dla.discovery.engine import discover


def _cfg(folder: Path) -> Config:
    return Config(
        source=SourceConfig(
            source_id="csv_fixture",
            display_name="CSV fixture",
            provider="csv_folder",
            csv_folder=CsvFolderConnectionConfig(folder=folder),
        )
    )


def _snapshot(bundle: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(p.relative_to(bundle)): (os.stat(p).st_mtime_ns, p.read_bytes())
        for p in sorted(bundle.rglob("*"))
        if p.is_file()
    }


# pandas' date-format inference warns on the fixture CSVs — connector-internal,
# not what these tests assert.
@pytest.mark.filterwarnings("ignore::UserWarning")
def test_discover_manifest_counts_match_disk(tmp_path: Path, fixtures_dir: Path) -> None:
    cfg = _cfg(fixtures_dir / "csv")
    bundle = tmp_path / "bundle"
    discover(cfg=cfg, connector=build_csv_folder(cfg.source.connection()), bundle_root=bundle)

    manifest = load_manifest(bundle)
    assert manifest is not None
    disk = count_artifacts_on_disk(bundle)
    assert manifest.artifact_counts == disk
    assert set(manifest.artifact_counts) == {at.value for at in ArtifactType}
    assert manifest.artifact_counts["table"] == disk["table"] > 0


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_discover_rerun_zero_diff_including_manifest(tmp_path: Path, fixtures_dir: Path) -> None:
    cfg = _cfg(fixtures_dir / "csv")
    bundle = tmp_path / "bundle"
    discover(cfg=cfg, connector=build_csv_folder(cfg.source.connection()), bundle_root=bundle)
    before = _snapshot(bundle)

    discover(cfg=cfg, connector=build_csv_folder(cfg.source.connection()), bundle_root=bundle)
    after = _snapshot(bundle)

    assert before == after  # zero diffs — not even mtimes (FR-016)
