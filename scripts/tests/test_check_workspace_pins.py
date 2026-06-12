"""The guard: every {workspace=true} source must have a version-ranged dependency entry."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_workspace_pins import find_unpinned_workspace_deps, main

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

NO_WORKSPACE_SOURCES = """
[project]
name = "x"
dependencies = ["pyyaml>=6"]
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


def test_no_workspace_sources_passes() -> None:
    """When there are no workspace sources, the check returns an empty list immediately."""
    assert find_unpinned_workspace_deps(NO_WORKSPACE_SOURCES) == []


# A dep string that starts with a character outside [A-Za-z0-9] won't match the
# internal regex — the `if not m: continue` branch (line 44) fires.
UNMATCHED_DEP_FORMAT = """
[project]
name = "x"
dependencies = ["-bad-dep-that-wont-match-regex"]
[tool.uv.sources]
auropro-core = { workspace = true }
"""


def test_dep_not_matching_name_regex_is_skipped() -> None:
    """A dep string with an invalid format (won't match the name regex) is skipped without error."""
    # auropro-core is a workspace dep but "-bad-dep..." doesn't contribute to pinned set
    result = find_unpinned_workspace_deps(UNMATCHED_DEP_FORMAT)
    assert result == ["auropro-core"]


def _write_pyproject(directory: Path, content: str) -> Path:
    """Write a pyproject.toml to a libs/<name>/ subdirectory."""
    pkg_dir = directory / "libs" / "mypkg"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    p = pkg_dir / "pyproject.toml"
    p.write_text(content, encoding="utf-8")
    return p


def test_main_returns_0_when_all_pinned(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """main() exits 0 and prints OK when every workspace dep has a version range."""
    _write_pyproject(tmp_path, GOOD)
    result = main(root=tmp_path)
    assert result == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_main_returns_1_with_violation_message(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """main() exits 1 and prints the violating package path when a dep is unpinned."""
    _write_pyproject(tmp_path, BARE)
    result = main(root=tmp_path)
    assert result == 1
    out = capsys.readouterr().out
    assert "auropro-core" in out
    assert "missing" in out.lower() or "version" in out.lower()


def test_main_uses_real_repo_root_when_no_root_given(capsys: pytest.CaptureFixture) -> None:
    """main() with no root argument derives root from __file__ and scans the real repo."""
    # The real repo passes its own pin checks — expect exit 0.
    result = main()
    assert result == 0
    out = capsys.readouterr().out
    assert "OK" in out
