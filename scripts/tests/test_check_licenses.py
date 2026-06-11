"""The license gate: denylisted packages must never appear in uv.lock."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_licenses import DENYLIST, find_denylisted

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
