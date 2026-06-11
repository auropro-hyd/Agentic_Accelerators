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

OPTIONAL_BARE = """
[project]
name = "x"
dependencies = []
[project.optional-dependencies]
extra = ["auropro-core"]
[tool.uv.sources]
auropro-core = { workspace = true }
"""

MARKER_NO_VERSION = """
[project]
name = "x"
dependencies = ["auropro-core; python_version >= '3.11'"]
[tool.uv.sources]
auropro-core = { workspace = true }
"""


def test_good_pyproject_passes() -> None:
    assert find_unpinned_workspace_deps(GOOD) == []


def test_bare_name_fails() -> None:
    assert find_unpinned_workspace_deps(BARE) == ["auropro-core"]


def test_missing_dependency_entry_fails() -> None:
    assert find_unpinned_workspace_deps(MISSING) == ["auropro-core"]


def test_optional_dependency_bare_fails() -> None:
    assert find_unpinned_workspace_deps(OPTIONAL_BARE) == ["auropro-core"]


def test_marker_without_version_fails() -> None:
    assert find_unpinned_workspace_deps(MARKER_NO_VERSION) == ["auropro-core"]
