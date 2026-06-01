"""US 4.2 — bulk-accept all Strong drafts in a table; coverage reflects it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright.sync_api")  # skip module if Playwright absent


@pytest.mark.ui
def test_bulk_accept_strong_updates_statuses_and_coverage(
    page: Any, live_server: tuple[str, Path]
) -> None:
    base_url, _bundle = live_server
    page.goto(f"{base_url}/tables/public.orders")

    # The only Strong pending draft is 'status'.
    page.click("text=Accept all Strong")
    page.wait_for_selector("text=Accepted 1")

    # Status flips to reviewed; navbar coverage shows 100% column descriptions.
    assert page.locator("span.pill.ok", has_text="reviewed").count() >= 1
    page.goto(f"{base_url}/")
    assert "100%" in page.content()
