"""US 4.1 — edit a column description in the browser; it lands in markdown."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter
import pytest

pytest.importorskip("playwright.sync_api")  # skip module if Playwright absent


@pytest.mark.ui
def test_inline_edit_writes_markdown_and_bumps_provenance(
    page: Any, live_server: tuple[str, Path]
) -> None:
    base_url, bundle = live_server
    page.goto(f"{base_url}/tables/public.orders/columns/status")

    page.fill("textarea[name=text]", "SME-authored meaning of order status.")
    page.click("button[type=submit]")
    page.wait_for_selector("text=Saved.")

    md = bundle / "descriptions" / "column.public.orders.status.md"
    post = frontmatter.loads(md.read_text(encoding="utf-8"))
    assert "SME-authored meaning of order status." in str(post.content)
    assert post["provenance"] == "ai-drafted-edited"
    assert post["created_by"] == "sme"
