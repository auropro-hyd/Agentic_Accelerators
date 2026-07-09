"""Discovery engine — connector observations to bundle artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from auropro_core.logging import get_logger, log_context

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ColumnPayload,
    CreatedBy,
    IndexPayload,
    NormalizedType,
    RelationshipPayload,
    SourcePayload,
    TablePayload,
)
from dla.bundle.writer import (
    WriteResult,
    now_utc,
    refresh_manifest_counts,
    write_artifact,
)
from dla.config.models import Config
from dla.connectors.base import (
    IntrospectionResult,
    RawColumn,
    RawIndex,
    RawRelationship,
    RawTable,
    SourceConnector,
)
from dla.discovery.relationships import infer_relationships
from dla.discovery.tagger import tag_declared

_log = get_logger("dla.discovery")


@dataclass
class DiscoveryReport:
    """Summary returned to the CLI for end-of-run printing."""

    source_id: str
    tables_written: int = 0
    columns_written: int = 0
    relationships_written: int = 0
    indexes_written: int = 0
    sme_skipped: int = 0
    write_results: list[WriteResult] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.write_results is None:
            self.write_results = []


def _table_artifact_id(source_id: str, table_name: str) -> str:
    return f"table:{table_name}"


def _column_artifact_id(source_id: str, table_name: str, column_name: str) -> str:
    return f"column:{table_name}:{column_name}"


def _index_artifact_id(source_id: str, table_name: str, index_name: str) -> str:
    return f"index:{table_name}:{index_name}"


def _relationship_artifact_id(
    source_id: str,
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
) -> str:
    return (
        f"relationship:{from_table}.{from_column}->{to_table}.{to_column}"
    )


def _table_payload(
    cfg: Config, now: datetime, table: RawTable
) -> TablePayload:
    return TablePayload(
        artifact_id=_table_artifact_id(cfg.source.source_id, table.name),
        source_id=cfg.source.source_id,
        provenance=Provenance.DISCOVERED,
        created_at=now,
        updated_at=now,
        created_by=CreatedBy.ACCELERATOR,
        name=table.name,
        column_names=[c.name for c in table.columns],
        pk_columns=list(table.pk_columns),
    )


def _column_payload(
    cfg: Config, now: datetime, table: RawTable, col: RawColumn
) -> ColumnPayload:
    return ColumnPayload(
        artifact_id=_column_artifact_id(cfg.source.source_id, table.name, col.name),
        source_id=cfg.source.source_id,
        provenance=Provenance.DISCOVERED,
        created_at=now,
        updated_at=now,
        created_by=CreatedBy.ACCELERATOR,
        name=col.name,
        table_ref=_table_artifact_id(cfg.source.source_id, table.name),
        data_type=col.data_type,
        normalized_type=NormalizedType(col.normalized_type),
        is_nullable=col.is_nullable,
        is_pk=col.is_pk,
        is_unique=col.is_unique,
    )


def _index_payload(
    cfg: Config, now: datetime, index: RawIndex
) -> IndexPayload:
    return IndexPayload(
        artifact_id=_index_artifact_id(cfg.source.source_id, index.table, index.name),
        source_id=cfg.source.source_id,
        provenance=Provenance.DISCOVERED,
        created_at=now,
        updated_at=now,
        created_by=CreatedBy.ACCELERATOR,
        name=index.name,
        table_ref=_table_artifact_id(cfg.source.source_id, index.table),
        columns=list(index.columns),
        is_unique=index.is_unique,
    )


def _table_body(cfg: Config, table: RawTable) -> str:
    return (
        f"# {table.name}\n\n"
        f"Discovered table from `{cfg.source.display_name}`. "
        f"{len(table.columns)} columns; primary key: "
        f"`{', '.join(table.pk_columns) if table.pk_columns else '(none declared)'}`.\n"
    )


def _column_body(table: RawTable, col: RawColumn) -> str:
    flags: list[str] = []
    if col.is_pk:
        flags.append("primary-key")
    if col.is_unique and not col.is_pk:
        flags.append("unique")
    if not col.is_nullable:
        flags.append("not-null")
    flag_str = ", ".join(flags) if flags else "no constraints"
    return (
        f"# {table.name}.{col.name}\n\n"
        f"`{col.data_type}` ({col.normalized_type}). {flag_str}.\n"
    )


def _relationship_body(
    rel_id: str, confidence: str, signals: list[str], composite_group: str | None = None
) -> str:
    body = (
        f"# {rel_id}\n\n"
        f"Confidence: **{confidence}**. Signals: {', '.join(signals) or '(none)'}.\n"
    )
    if composite_group:
        body += f"Part of composite foreign key `{composite_group}`.\n"
    return body


def _rel_key(rel: RawRelationship) -> tuple[str, str, str, str]:
    return (rel.from_table, rel.from_column, rel.to_table, rel.to_column)


def _composite_groups(
    rels: list[RawRelationship],
) -> dict[tuple[str, str, str, str], str]:
    """Map relationship key -> composite-group id for every declared
    relationship that is one column pair of a multi-column FK (D13).

    Column pairs belong to the same composite FK when they share a source
    table, target table, and constraint name (a SQL composite FK is one named
    constraint, so its per-column halves arrive with an identical `name`).
    The group id is deterministic — `fkgroup:<from_table>:<constraint_name>`
    — so re-runs always produce the same id (idempotency, FR-016; the sorted
    column set would work equally, the constraint name is simply more
    readable). Relationships without a
    constraint name are never grouped: without the name two independent
    single-column FKs onto the same table would be indistinguishable from a
    composite, and inventing a composite would be worse than flattening one.
    """
    by_constraint: dict[tuple[str, str, str], list[RawRelationship]] = {}
    for rel in rels:
        if rel.name:
            by_constraint.setdefault((rel.from_table, rel.to_table, rel.name), []).append(rel)

    groups: dict[tuple[str, str, str, str], str] = {}
    for (from_table, _to_table, name), members in by_constraint.items():
        if len(members) < 2:
            continue  # single-column FK — no compositeness to preserve
        group_id = f"fkgroup:{from_table}:{name}"
        for m in members:
            groups[_rel_key(m)] = group_id
    return groups


def _index_body(index: RawIndex) -> str:
    flag = "unique" if index.is_unique else "non-unique"
    return (
        f"# {index.name}\n\n"
        f"{flag} index on `{index.table}` over column(s): {', '.join(index.columns)}.\n"
    )


def discover(
    *,
    cfg: Config,
    connector: SourceConnector,
    bundle_root: Path,
    dry_run: bool = False,
) -> DiscoveryReport:
    """Drive a full discovery pass and write the bundle.

    Steps:
      1. Connect (errors surface as `connectors.base.ConnectionError`).
      2. Introspect the schema.
      3. Infer relationships (with confidence tags + signals).
      4. Emit artifacts via the atomic bundle writer.
      5. Write/refresh `bundle.json`.
    """
    report = DiscoveryReport(source_id=cfg.source.source_id)

    with log_context(source_id=cfg.source.source_id, step="discover"):
        _log.info("connecting", provider=cfg.source.provider)
        connector.connect()
        try:
            _log.info("introspecting")
            intro: IntrospectionResult = connector.introspect_schema()
            _log.info(
                "introspected",
                tables=len(intro.tables),
                declared_relationships=len(intro.declared_relationships),
                indexes=len(intro.indexes),
            )
            inferred = infer_relationships(
                intro, thresholds=cfg.thresholds, connector=connector
            )
            _log.info("relationships_inferred", count=len(inferred))
        finally:
            pass  # leave connection management to the caller via the orchestrator

        now = now_utc()

        if dry_run:
            report.tables_written = len(intro.tables)
            report.columns_written = sum(len(t.columns) for t in intro.tables)
            report.relationships_written = len(intro.declared_relationships) + len(inferred)
            report.indexes_written = len(intro.indexes)
            connector.close()
            return report

        # Write artifacts. Sort everything for stable on-disk order (idempotency).
        for table in intro.tables:
            with log_context(artifact_id=_table_artifact_id(cfg.source.source_id, table.name)):
                res = write_artifact(
                    bundle_root, _table_payload(cfg, now, table), body=_table_body(cfg, table)
                )
                report.write_results.append(res)
                if res.skipped_to_preserve_sme:
                    report.sme_skipped += 1
                else:
                    report.tables_written += 1
                for col in table.columns:
                    cres = write_artifact(
                        bundle_root,
                        _column_payload(cfg, now, table, col),
                        body=_column_body(table, col),
                    )
                    report.write_results.append(cres)
                    if cres.skipped_to_preserve_sme:
                        report.sme_skipped += 1
                    else:
                        report.columns_written += 1

        # Declared FKs. Multi-column FKs arrive as one RawRelationship per
        # column pair; `composite_group` re-links the pairs (D13).
        composite_groups = _composite_groups(intro.declared_relationships)
        for rel in intro.declared_relationships:
            rel_id = _relationship_artifact_id(
                cfg.source.source_id, rel.from_table, rel.from_column, rel.to_table, rel.to_column
            )
            tag = tag_declared()
            composite_group = composite_groups.get(_rel_key(rel))
            payload = RelationshipPayload(
                artifact_id=rel_id,
                source_id=cfg.source.source_id,
                provenance=Provenance.DISCOVERED,
                confidence=tag.confidence,  # type: ignore[arg-type]
                created_at=now,
                updated_at=now,
                created_by=CreatedBy.ACCELERATOR,
                from_column_ref=_column_artifact_id(cfg.source.source_id, rel.from_table, rel.from_column),
                to_column_ref=_column_artifact_id(cfg.source.source_id, rel.to_table, rel.to_column),
                relationship_type="declared_fk",
                signals=tag.signals,
                composite_group=composite_group,
            )
            res = write_artifact(
                bundle_root,
                payload,
                body=_relationship_body(rel_id, tag.confidence, tag.signals, composite_group),
            )
            report.write_results.append(res)
            if not res.skipped_to_preserve_sme:
                report.relationships_written += 1

        # Inferred relationships.
        for inf in inferred:
            r = inf.relationship
            rel_id = _relationship_artifact_id(
                cfg.source.source_id, r.from_table, r.from_column, r.to_table, r.to_column
            )
            payload = RelationshipPayload(
                artifact_id=rel_id,
                source_id=cfg.source.source_id,
                provenance=Provenance.DISCOVERED,
                confidence=inf.tag.confidence,  # type: ignore[arg-type]
                created_at=now,
                updated_at=now,
                created_by=CreatedBy.ACCELERATOR,
                from_column_ref=_column_artifact_id(cfg.source.source_id, r.from_table, r.from_column),
                to_column_ref=_column_artifact_id(cfg.source.source_id, r.to_table, r.to_column),
                relationship_type="inferred_fk",
                signals=inf.tag.signals,
            )
            res = write_artifact(bundle_root, payload, body=_relationship_body(rel_id, inf.tag.confidence, inf.tag.signals))
            report.write_results.append(res)
            if not res.skipped_to_preserve_sme:
                report.relationships_written += 1

        # Indexes.
        for index in intro.indexes:
            ipayload = _index_payload(cfg, now, index)
            res = write_artifact(bundle_root, ipayload, body=_index_body(index))
            report.write_results.append(res)
            if not res.skipped_to_preserve_sme:
                report.indexes_written += 1

        # Source artifact + manifest.
        source_payload = SourcePayload(
            artifact_id=f"source:{cfg.source.source_id}",
            source_id=cfg.source.source_id,
            provenance=Provenance.DISCOVERED,
            created_at=now,
            updated_at=now,
            created_by=CreatedBy.ACCELERATOR,
            provider=cfg.source.provider,
            display_name=cfg.source.display_name,
            connection_config_ref="(redacted)",
            discovered_at=now,
            summary_counts={
                "tables": report.tables_written,
                "columns": report.columns_written,
                "relationships": report.relationships_written,
                "indexes": report.indexes_written,
            },
        )
        write_artifact(bundle_root, source_payload, body=f"# Source: {cfg.source.display_name}\n")

        # Manifest counts are recounted from disk (not from this run's write
        # tally) so they stay correct even when artifacts are SME-preserved,
        # and so every artifact type — not just the schema ones — is covered.
        refresh_manifest_counts(bundle_root, source_id=cfg.source.source_id)

        connector.close()

    return report
