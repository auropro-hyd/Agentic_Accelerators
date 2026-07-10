#!/usr/bin/env python3
"""Guard: top-level contracts/ must byte-mirror every published app schema.

Each accelerator publishes its machine-readable contract at
apps/<name>/config/schemas/*.json (generated from code, parity-tested).
contracts/ mirrors those files so downstream consumers can pin two JSON
files without learning the repo tree. This guard fails CI when the mirror
is missing, differs, or carries stale files no app publishes.

Usage: python scripts/check_contract_mirror.py [--fix]
       (--fix rewrites contracts/ from the app schemas; exit 1 on violations)
"""

from __future__ import annotations

import sys
from pathlib import Path


def expected_mirrors(root: Path) -> dict[Path, Path]:
    """Map contracts/<filename> -> its source apps/*/config/schemas/<filename>."""
    mapping: dict[Path, Path] = {}
    for source in sorted(root.glob("apps/*/config/schemas/*.json")):
        target = root / "contracts" / source.name
        if target in mapping:
            raise ValueError(
                f"schema filename collision: {source.name} published by more than one app"
            )
        mapping[target] = source
    return mapping


def find_mirror_problems(root: Path) -> list[str]:
    """Return human-readable violations (empty list == mirror is faithful)."""
    problems: list[str] = []
    mapping = expected_mirrors(root)
    for target, source in mapping.items():
        rel = target.relative_to(root)
        if not target.exists():
            problems.append(f"missing mirror: {rel} (source: {source.relative_to(root)})")
        elif target.read_bytes() != source.read_bytes():
            problems.append(f"mirror differs: {rel} != {source.relative_to(root)}")
    contracts_dir = root / "contracts"
    if contracts_dir.is_dir():
        for existing in sorted(contracts_dir.glob("*.json")):
            if existing not in mapping:
                problems.append(f"stale mirror: {existing.relative_to(root)} has no app source")
    return problems


def fix(root: Path) -> None:
    """Rewrite contracts/ to mirror the app schemas (and drop stale files)."""
    contracts_dir = root / "contracts"
    contracts_dir.mkdir(exist_ok=True)
    mapping = expected_mirrors(root)
    for target, source in mapping.items():
        target.write_bytes(source.read_bytes())
    for existing in sorted(contracts_dir.glob("*.json")):
        if existing not in mapping:
            existing.unlink()


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if root is None:
        root = Path(__file__).resolve().parent.parent
    if "--fix" in args:
        fix(root)
    problems = find_mirror_problems(root)
    if problems:
        print("contracts/ mirror violations (run: make sync-contracts):")
        print("\n".join(f"  {p}" for p in problems))
        return 1
    print("check_contract_mirror: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
