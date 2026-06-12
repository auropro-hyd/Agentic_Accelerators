#!/usr/bin/env python3
"""Guard: every `{ workspace = true }` uv source must also carry an explicit
version range in [project].dependencies or [project.optional-dependencies].

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

    # Collect deps from [project].dependencies AND all [project.optional-dependencies] groups.
    project = data.get("project", {})
    all_deps: list[str] = list(project.get("dependencies", []))
    for group_deps in project.get("optional-dependencies", {}).values():
        all_deps.extend(group_deps)

    pinned: set[str] = set()
    # Name is everything up to the first version operator, '[' (extras), ';' (marker),
    # or whitespace.  Everything after the name is checked for a version operator.
    _name_re = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)([<>=!~\[\s;].*)?$")
    for dep in all_deps:
        m = _name_re.match(dep)
        if not m:
            continue
        name = m.group(1)
        rest = dep[len(name):]  # everything after the bare name
        # A dep is pinned only if there is a version operator in the specifier part
        # (before any ';' environment marker).
        specifier_part = rest.split(";")[0] if ";" in rest else rest
        if re.search(r"[<>=!~]", specifier_part):
            pinned.add(name.lower().replace("_", "-"))

    return sorted(
        pkg for pkg in workspace_pkgs
        if pkg.lower().replace("_", "-") not in pinned
    )


def main(root: Path | None = None) -> int:
    if root is None:
        root = Path(__file__).resolve().parent.parent
    failures: list[str] = []
    for pyproject in sorted(
        [*root.glob("libs/*/pyproject.toml"), *root.glob("apps/*/pyproject.toml")]
    ):
        unpinned = find_unpinned_workspace_deps(pyproject.read_text(encoding="utf-8"))
        failures.extend(f"{pyproject.relative_to(root)}: {pkg}" for pkg in unpinned)
    if failures:
        print("Workspace deps missing an explicit version range in [project].dependencies:")
        print("\n".join(f"  {f}" for f in failures))
        return 1
    print("check_workspace_pins: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
