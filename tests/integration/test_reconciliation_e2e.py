"""M5 — reconciliation end-to-end (T115): match / conflict / gap buckets."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dla.bundle.provenance import Provenance
from dla.bundle.schema import ColumnPayload, CreatedBy, NormalizedType, TablePayload
from dla.bundle.writer import write_artifact
from dla.importers.csv_dictionary import import_dictionary
from dla.importers.normalize import normalize_and_write
from dla.reconciliation import reconcile

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "client_docs" / "data_dictionary.csv"
_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)


def _col(table: str, name: str, ntype: NormalizedType) -> ColumnPayload:
    return ColumnPayload(
        artifact_id=f"column:{table}:{name}",
        provenance=Provenance.DISCOVERED,
        name=name,
        table_ref=f"table:{table}",
        data_type=str(ntype),
        normalized_type=ntype,
        is_nullable=True,
        is_pk=name == "id",
        is_unique=name == "id",
        **_C,
    )


def _seed_schema(bundle: Path) -> None:
    write_artifact(
        bundle,
        TablePayload(
            artifact_id="table:public.orders", provenance=Provenance.DISCOVERED,
            name="public.orders", column_names=["id", "status", "customer_id"], **_C,
        ),
        body="t",
    )
    write_artifact(
        bundle,
        TablePayload(
            artifact_id="table:public.customers", provenance=Provenance.DISCOVERED,
            name="public.customers", column_names=["email"], **_C,
        ),
        body="t",
    )
    for c in (
        _col("public.orders", "id", NormalizedType.INTEGER),
        _col("public.orders", "status", NormalizedType.STRING),
        _col("public.orders", "customer_id", NormalizedType.INTEGER),
        _col("public.customers", "email", NormalizedType.STRING),
    ):
        write_artifact(bundle, c, body="c")


def test_reconcile_buckets(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_schema(bundle)
    records, _ = import_dictionary(_FIX)
    normalize_and_write(bundle_root=bundle, raws=records, source_id="s")

    results = reconcile(bundle, source_id="s")
    by_ref = {r.imported_ref: str(r.bucket) for r in results}

    # status (varchar↔string) → match; email → match
    assert by_ref["imported_artifact:csv_dictionary:public.orders:status"] == "match"
    assert by_ref["imported_artifact:csv_dictionary:public.customers:email"] == "match"
    # id: doc 'varchar' vs discovered integer → conflict
    assert by_ref["imported_artifact:csv_dictionary:public.orders:id"] == "conflict"
    # discount_pct: no such column → gap-doc-only
    assert by_ref["imported_artifact:csv_dictionary:public.orders:discount_pct"] == "gap-doc-only"
    # customer_id is in a documented table but undocumented → gap-source-only
    assert by_ref["column:public.orders:customer_id"] == "gap-source-only"
