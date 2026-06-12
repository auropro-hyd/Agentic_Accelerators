"""The license gate: denylisted packages must never appear in uv.lock."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_licenses import DENYLIST, find_denylisted, main

CLEAN_LOCK = """
version = 1
[[package]]
name = "pydantic"
version = "2.7.0"
[[package]]
name = "litellm"
version = "1.88.1"
"""

DIRTY_LOCK = """
version = 1
[[package]]
name = "pymupdf"
version = "1.27.0"
[[package]]
name = "marker-pdf"
version = "1.10.2"
"""


def test_clean_lock_passes() -> None:
    assert find_denylisted(CLEAN_LOCK) == []


def test_denylisted_packages_detected() -> None:
    assert find_denylisted(DIRTY_LOCK) == ["marker-pdf", "pymupdf"]


def test_denylist_covers_known_traps() -> None:
    for trap in ("pymupdf", "marker-pdf", "surya-ocr", "ultralytics", "fitz"):
        assert trap in DENYLIST


def test_main_returns_0_on_clean_lock(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """main() exits 0 and prints OK when uv.lock contains no denylisted packages."""
    lock = tmp_path / "uv.lock"
    lock.write_text(CLEAN_LOCK, encoding="utf-8")
    result = main(root=tmp_path)
    assert result == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_main_returns_1_on_dirty_lock(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """main() exits 1 and prints the denylisted package names when uv.lock has violations."""
    lock = tmp_path / "uv.lock"
    lock.write_text(DIRTY_LOCK, encoding="utf-8")
    result = main(root=tmp_path)
    assert result == 1
    out = capsys.readouterr().out
    assert "pymupdf" in out
    assert "DENYLISTED" in out


def test_main_uses_real_repo_root_when_no_root_given(capsys: pytest.CaptureFixture) -> None:
    """main() with no root argument derives root from __file__ and reads the real uv.lock."""
    # The real repo has a clean uv.lock — expect exit 0.
    result = main()
    assert result == 0
    out = capsys.readouterr().out
    assert "OK" in out
