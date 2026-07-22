"""Fake-boundary test harness for Playwright Web Search.

The single seam is the Playwright client (``browserType.connect`` and the browser /
context / page it hands back) plus the SearXNG HTTP response. Faking those two makes the
whole render pipeline testable with no real Chromium and no network. This module
establishes that pattern as the baseline for later tickets.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest

# The pytest-homeassistant-custom-component plugin provides the `hass` fixture etc.
pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> None:
    """Enable loading of the custom integration in every test."""
    return


# --- Fake Playwright client -------------------------------------------------------


@dataclass
class FakePage:
    """A fake Playwright page returning canned rendered content.

    ``goto_error`` lets a test simulate a navigation failure (e.g. a
    ``PlaywrightTimeoutError``) while ``evaluate`` still returns the canned partial
    content — the injected extraction JS runs against whatever is in the DOM.
    """

    body_text: str = "canned rendered text"
    page_title: str = "Canned Title"
    url: str = "https://example.com/final"
    goto_error: Exception | None = None

    async def goto(
        self, url: str, wait_until: str | None = None, timeout: int | None = None
    ) -> None:
        if self.goto_error is not None:
            raise self.goto_error
        return None

    async def evaluate(self, script: str) -> dict[str, Any]:
        # Stands in for the injected extraction JS (real fidelity isn't unit-testable
        # through a fake); returns the canned title/text the render path assembles from.
        return {"title": self.page_title, "text": self.body_text}


@dataclass
class FakeContext:
    """A fake browser context that yields a preconfigured page."""

    page: FakePage

    async def new_page(self) -> FakePage:
        return self.page


@dataclass
class FakeBrowser:
    """A fake browser; records that it was closed (connect-per-call teardown)."""

    page: FakePage
    closed: bool = False

    async def new_context(self) -> FakeContext:
        return FakeContext(self.page)

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeBrowserType:
    """Fake ``chromium`` browser type; ``connect`` returns a fake browser."""

    page: FakePage
    connect_error: Exception | None = None
    connect_calls: list[str] = field(default_factory=list)
    browsers: list[FakeBrowser] = field(default_factory=list)

    async def connect(self, ws_url: str, timeout: int | None = None) -> FakeBrowser:
        self.connect_calls.append(ws_url)
        if self.connect_error is not None:
            raise self.connect_error
        browser = FakeBrowser(self.page)
        self.browsers.append(browser)
        return browser


@dataclass
class FakePlaywright:
    """Fake object returned by ``async_playwright().__aenter__``."""

    chromium: FakeBrowserType


def make_async_playwright(
    page: FakePage, connect_error: Exception | None = None
) -> tuple[Any, FakeBrowserType]:
    """Build a fake ``async_playwright`` context manager and its browser type."""
    browser_type = FakeBrowserType(page=page, connect_error=connect_error)

    @asynccontextmanager
    async def _fake_async_playwright() -> Any:
        yield FakePlaywright(chromium=browser_type)

    return _fake_async_playwright, browser_type


@pytest.fixture
def fake_page() -> FakePage:
    """Return a default fake page."""
    return FakePage()


@pytest.fixture
def patch_playwright(fake_page: FakePage) -> Generator[FakeBrowserType, None, None]:
    """Patch render.async_playwright with a fake; yield the browser type for asserts."""
    factory, browser_type = make_async_playwright(fake_page)
    with patch(
        "custom_components.playwright_websearch.render.async_playwright",
        new=factory,
    ):
        yield browser_type


# --- Fake SearXNG response --------------------------------------------------------
# Established now for later tickets (search_web); open_url does not use it yet.


def fake_searxng_response(
    results: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Return a minimal SearXNG-shaped JSON response."""
    if results is None:
        results = [
            {
                "url": "https://example.com/a",
                "title": "Result A",
                "content": "Snippet A",
            }
        ]
    return {"results": results}
