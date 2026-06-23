"""US 5.3 — resolve an import conflict in the browser (T121)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter
import pytest

pytest.importorskip("playwright.sync_api")  # skip module if Playwright absent


@pytest.mark.ui
def test_resolve_conflict_doc_side_writes_reconciled(
    page: Any, live_server: tuple[str, Path]
) -> None:
    base_url, bundle = live_server
    page.goto(f"{base_url}/imports/conflicts")
    page.get_by_role("link", name="Resolve").first.click()
    page.wait_for_selector("text=Client documentation")
    page.get_by_role("button", name="Use doc").click()
    page.wait_for_selector("text=resolved")

    # The chosen doc text becomes an sme-authored description on disk.
    md = bundle / "descriptions" / "column.public.orders.status.md"
    post = frontmatter.loads(md.read_text(encoding="utf-8"))
    assert "Numeric status code" in str(post.content)
    assert post["provenance"] == "sme-authored"
