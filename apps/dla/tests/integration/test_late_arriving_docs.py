"""M7 — late-arriving docs / re-import preserves prior SME-reconciled work (T162).

Re-running import must not re-evaluate artifacts an SME already reconciled. This
is enforced by the provenance writer: `client-provided-reconciled` is preserve-
worthy, so a fresh `client-provided` re-import is skipped, not clobbered.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType, SourceFormat
from dla.importers import RawImport
from dla.importers.normalize import normalize_and_write

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _raw(value: str) -> RawImport:
    return RawImport(
        source_format=SourceFormat.CSV_DICTIONARY,
        source_path="dict.csv",
        target_artifact_type=ArtifactType.DESCRIPTION,
        target_ref="column:public.orders:status",
        proposed_value=value,
        raw_payload={"data_type": "varchar"},
    )


def test_reimport_preserves_prior_reconciled(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    # First import.
    normalize_and_write(bundle_root=bundle, raws=[_raw("doc v1")], source_id="s")
    imp = iter_artifacts(bundle, ArtifactType.IMPORTED_ARTIFACT)[0]

    # SME reconciles it -> client-provided-reconciled (preserve-worthy).
    from dla.bundle.writer import write_artifact

    reconciled = imp.model_copy(
        update={"provenance": Provenance.CLIENT_PROVIDED_RECONCILED, "updated_at": _TS}
    )
    write_artifact(bundle, reconciled, body=imp.proposed_value, force=True)

    # A late re-import of the same item must NOT overwrite the reconciled one.
    normalize_and_write(bundle_root=bundle, raws=[_raw("doc v2 (late)")], source_id="s")
    after = iter_artifacts(bundle, ArtifactType.IMPORTED_ARTIFACT)[0]
    assert after.provenance == Provenance.CLIENT_PROVIDED_RECONCILED
    assert after.proposed_value == "doc v1"  # the reconciled value, not the late re-import
