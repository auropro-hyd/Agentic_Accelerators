#!/usr/bin/env python3
"""Guard: every `{ workspace = true }` uv source must also carry an explicit
version range in [project].dependencies.

uv strips tool.uv.sources from built wheels and does NOT auto-pin sibling
versions (astral-sh/uv#9811) — without the explicit range, published wheels
ship a bare, unpinned internal dependency.

Usage: python scripts/check_workspace_pins.py  (exit 1 on violations)
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


def find_unpinned_workspace_deps(pyproject_text: str) -> list[str]:
    """Return workspace-sourced package names lacking a version-ranged dep entry."""
    data = tomllib.loads(pyproject_text)
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    workspace_pkgs = {
        name for name, spec in sources.items()
        if isinstance(spec, dict) and spec.get("workspace") is True
    }
    if not workspace_pkgs:
        return []

    deps = data.get("project", {}).get("dependencies", [])
    pinned: set[str] = set()
    for dep in deps:
        m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*)$", dep)
        if not m:
            continue
        name, rest = m.group(1), m.group(2).strip()
        if rest:  # any specifier counts as pinned
            pinned.add(name.lower().replace("_", "-"))

    return sorted(
        pkg for pkg in workspace_pkgs
        if pkg.lower().replace("_", "-") not in pinned
    )


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    failures: list[str] = []
    for pyproject in sorted(root.glob("*/*/pyproject.toml")):  # libs/*, apps/*
        unpinned = find_unpinned_workspace_deps(pyproject.read_text(encoding="utf-8"))
        failures.extend(f"{pyproject.relative_to(root)}: {pkg}" for pkg in unpinned)
    if failures:
        print("Workspace deps missing an explicit version range in [project].dependencies:")
        print("\n".join(f"  {f}" for f in failures))
        return 1
    print("check_workspace_pins: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
