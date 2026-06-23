"""SME term-mapping rules (M7, T158/T166).

Rules map a column/table *name* pattern to a glossary term and are consulted
**before** any heuristic fuzzy match (FR-021). Patterns match names only —
`pattern_kind: regex` is evaluated against artifact names, never against data
values (T166). Higher `precedence` wins.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType, CreatedBy, PatternKind, TermMappingRulePayload
from dla.bundle.writer import write_artifact


def _name_of(ref: str) -> str:
    """`column:public.orders:ord_dt` -> `ord_dt`; a bare name passes through."""
    return ref.rsplit(":", 1)[-1] if ":" in ref else ref


def load_rules(bundle_root: Path) -> list[TermMappingRulePayload]:
    """All term-mapping rules, highest precedence first (stable by pattern)."""
    rules = cast(
        list[TermMappingRulePayload],
        iter_artifacts(bundle_root, ArtifactType.TERM_MAPPING_RULE),
    )
    return sorted(rules, key=lambda r: (-r.precedence, r.pattern))


def _matches(rule: TermMappingRulePayload, name: str) -> bool:
    if rule.pattern_kind == PatternKind.EXACT:
        return name == rule.pattern
    if rule.pattern_kind == PatternKind.GLOB:
        return fnmatch.fnmatch(name, rule.pattern)
    # regex — matched against the NAME only, never data values (T166)
    try:
        return re.search(rule.pattern, name) is not None
    except re.error:
        return False


def resolve_term(name_or_ref: str, rules: list[TermMappingRulePayload]) -> str | None:
    """Return the glossary term mapped by the highest-precedence matching rule, or None.

    A non-None result is authoritative — the caller must NOT fall back to fuzzy
    matching when a rule matches (FR-021).
    """
    name = _name_of(name_or_ref)
    for rule in rules:  # already precedence-sorted
        if _matches(rule, name):
            return rule.target_glossary_term
    return None


def _rule_id(pattern: str, target_glossary_term: str) -> str:
    digest = hashlib.sha1(f"{pattern}|{target_glossary_term}".encode()).hexdigest()[:8]
    return f"term_mapping_rule:{digest}"


def save_rule(
    *,
    bundle_root: Path,
    source_id: str,
    pattern: str,
    pattern_kind: PatternKind | str,
    target_glossary_term: str,
    scope: dict[str, Any] | None = None,
    precedence: int = 0,
    sme_name: str | None = None,
) -> TermMappingRulePayload:
    now = datetime.now(UTC)
    rule = TermMappingRulePayload(
        artifact_id=_rule_id(pattern, target_glossary_term),
        source_id=source_id,
        provenance=Provenance.SME_AUTHORED,
        created_at=now,
        updated_at=now,
        created_by=CreatedBy.SME,
        created_by_detail=sme_name,
        pattern=pattern,
        pattern_kind=PatternKind(pattern_kind),
        target_glossary_term=target_glossary_term,
        scope=scope or {"tables": "*", "columns": "*"},
        precedence=precedence,
    )
    write_artifact(bundle_root, rule, body=f"`{pattern}` → {target_glossary_term}", force=True)
    return rule


def delete_rule(bundle_root: Path, rule_id: str) -> bool:
    """Remove a term-mapping rule's artifact files. Returns True if removed."""
    from dla.bundle.layout import paths_for

    md_path, json_path = paths_for(bundle_root, rule_id, ArtifactType.TERM_MAPPING_RULE)
    removed = False
    for p in (md_path, json_path):
        if p.exists():
            p.unlink()
            removed = True
    return removed
