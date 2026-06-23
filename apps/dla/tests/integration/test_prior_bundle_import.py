"""M7 — prior-bundle import (T157): inherit reviewable artifacts, preserve newer SME work."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    BundleManifest,
    CreatedBy,
    DescriptionPayload,
    GlossaryEntryPayload,
)
from dla.bundle.writer import write_artifact, write_manifest
from dla.importers.normalize import import_prior_bundle

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _glossary(source_id: str, definition: str, prov: Provenance) -> GlossaryEntryPayload:
    return GlossaryEntryPayload(
        artifact_id="glossary_entry:cust", source_id=source_id, provenance=prov,
        created_at=_TS, updated_at=_TS, created_by=CreatedBy.SME, term="cust",
        definition=definition, usages=[], recurrence_count=3,
    )


def _desc(source_id: str, text: str, prov: Provenance) -> DescriptionPayload:
    return DescriptionPayload(
        artifact_id="description:column:public.orders:status", source_id=source_id,
        provenance=prov, created_at=_TS, updated_at=_TS,
        created_by=CreatedBy.SME if prov != Provenance.AI_DRAFTED else CreatedBy.ACCELERATOR,
        target_artifact_ref="column:public.orders:status", target_kind="column", text=text,
    )


def test_inherits_with_imported_from_and_preserved_provenance(tmp_path: Path) -> None:
    prior, new = tmp_path / "prior", tmp_path / "new"
    prior.mkdir()
    new.mkdir()
    write_artifact(prior, _glossary("prior_src", "Customer.", Provenance.SME_AUTHORED), body="Customer.")
    write_artifact(prior, _desc("prior_src", "Order status.", Provenance.AI_DRAFTED_EDITED),
                   body="Order status.", md_exclude_keys={"text"})
    write_manifest(prior, BundleManifest(source_id="prior_src", last_run_at=_TS, bundle_root=str(prior)))

    report = import_prior_bundle(bundle_root=new, prior_root=prior)
    assert report.written == 2

    g = iter_artifacts(new, ArtifactType.GLOSSARY_ENTRY)[0]
    assert g.imported_from == "prior_src" and g.provenance == Provenance.SME_AUTHORED
    d = iter_artifacts(new, ArtifactType.DESCRIPTION)[0]
    assert d.imported_from == "prior_src" and d.provenance == Provenance.AI_DRAFTED_EDITED


def test_prior_bundle_does_not_clobber_newer_sme_work(tmp_path: Path) -> None:
    prior, new = tmp_path / "prior", tmp_path / "new"
    prior.mkdir()
    new.mkdir()
    # New bundle already has an SME-authored description; prior has an older ai-drafted one.
    write_artifact(new, _desc("new_src", "NEW sme text", Provenance.SME_AUTHORED),
                   body="NEW sme text", md_exclude_keys={"text"})
    write_artifact(prior, _desc("prior_src", "OLD draft", Provenance.AI_DRAFTED),
                   body="OLD draft", md_exclude_keys={"text"})

    report = import_prior_bundle(bundle_root=new, prior_root=prior)
    assert report.skipped >= 1
    d = iter_artifacts(new, ArtifactType.DESCRIPTION)[0]
    assert d.text == "NEW sme text" and d.provenance == Provenance.SME_AUTHORED
