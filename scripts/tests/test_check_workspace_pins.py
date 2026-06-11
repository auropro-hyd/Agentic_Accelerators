"""The guard: every {workspace=true} source must have a version-ranged dependency entry."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_workspace_pins import find_unpinned_workspace_deps

GOOD = """
[project]
name = "x"
dependencies = ["auropro-core>=0.1,<0.2", "pyyaml>=6"]
[tool.uv.sources]
auropro-core = { workspace = true }
"""

BARE = """
[project]
name = "x"
dependencies = ["auropro-core", "pyyaml>=6"]
[tool.uv.sources]
auropro-core = { workspace = true }
"""

MISSING = """
[project]
name = "x"
dependencies = ["pyyaml>=6"]
[tool.uv.sources]
auropro-core = { workspace = true }
"""


def test_good_pyproject_passes() -> None:
    assert find_unpinned_workspace_deps(GOOD) == []


def test_bare_name_fails() -> None:
    assert find_unpinned_workspace_deps(BARE) == ["auropro-core"]


def test_missing_dependency_entry_fails() -> None:
    assert find_unpinned_workspace_deps(MISSING) == ["auropro-core"]
