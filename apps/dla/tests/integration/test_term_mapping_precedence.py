"""M7 — term-mapping rules take precedence over fuzzy matching (T161/FR-021)."""

from __future__ import annotations

from pathlib import Path

from dla.reconciliation.term_mapping import load_rules, resolve_term, save_rule


def test_glob_rule_resolves_term_no_fuzzy(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    save_rule(
        bundle_root=bundle, source_id="s", pattern="*_dt", pattern_kind="glob",
        target_glossary_term="order_date", precedence=10,
    )
    rules = load_rules(bundle)
    # A rule match is authoritative — the caller never reaches fuzzy matching.
    assert resolve_term("column:public.orders:ord_dt", rules) == "order_date"
    assert resolve_term("created_dt", rules) == "order_date"
    # No rule matches -> None (caller may then fall back to fuzzy).
    assert resolve_term("status", rules) is None


def test_higher_precedence_wins(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    save_rule(bundle_root=bundle, source_id="s", pattern="cust_id", pattern_kind="exact",
              target_glossary_term="generic_id", precedence=1)
    save_rule(bundle_root=bundle, source_id="s", pattern="cust_*", pattern_kind="glob",
              target_glossary_term="customer_identifier", precedence=10)
    rules = load_rules(bundle)
    assert resolve_term("cust_id", rules) == "customer_identifier"  # precedence 10 > 1
