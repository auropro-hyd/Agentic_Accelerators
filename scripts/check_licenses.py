#!/usr/bin/env python3
"""License gate, two layers:

1. DENYLIST (hard fail): packages whose licenses are unshippable for client
   deliverables — AGPL (pymupdf/fitz, ultralytics) and revenue-capped OpenRAIL
   weights (marker-pdf, surya-ocr) — must never enter uv.lock.
   Policy: docs/ACCELERATOR-REPO-PLAN.md §5.

2. ALLOWLIST (via pip-licenses, run separately in CI): installed packages must
   carry MIT/Apache/BSD/ISC/PSF licenses. First-party + verified exceptions
   live in scripts/license_ignore.txt (one package name per line, '#' comments).

Usage: python scripts/check_licenses.py  (exit 1 on denylist hit)
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

DENYLIST: frozenset[str] = frozenset({
    "pymupdf",        # AGPL-3.0 (Artifex)
    "fitz",           # PyMuPDF import alias package
    "marker-pdf",     # GPL-3.0 + revenue-capped OpenRAIL weights ($2M)
    "surya-ocr",      # revenue-capped OpenRAIL weights ($5M)
    "ultralytics",    # AGPL-3.0 (leaks in via unstructured[hi_res])
})


def find_denylisted(lock_text: str) -> list[str]:
    """Return denylisted package names present in a uv.lock document."""
    data = tomllib.loads(lock_text)
    names = {pkg.get("name", "").lower() for pkg in data.get("package", [])}
    return sorted(names & DENYLIST)


def main() -> int:
    lock = Path(__file__).resolve().parent.parent / "uv.lock"
    hits = find_denylisted(lock.read_text(encoding="utf-8"))
    if hits:
        print("DENYLISTED packages found in uv.lock (see docs/ACCELERATOR-REPO-PLAN.md §5):")
        print("\n".join(f"  {h}" for h in hits))
        return 1
    print("check_licenses: OK (no denylisted packages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
