"""Test render_page's structured result shape through the faked Playwright boundary.

These assert on the internal ``RenderResult`` keys (``status`` / ``word_count`` /
``final_url``) directly — ``open_url`` remaps and hides some of those, so the render
contract (ADR 0003) is exercised here rather than through the tool.
"""

from __future__ import annotations

from unittest.mock import patch

from custom_components.playwright_websearch.pw_client import (
    TimeoutError as PlaywrightTimeoutError,
)

from custom_components.playwright_websearch.render import render_page

from .conftest import FakePage, make_async_playwright

WS_URL = "ws://playwright.local:3000"


async def _render(page: FakePage, *, content_floor: int = 50, **kwargs):
    """Render ``page`` through a fresh faked boundary."""
    factory, _bt = make_async_playwright(page, **kwargs)
    with patch(
        "custom_components.playwright_websearch.render.async_playwright",
        new=factory,
    ):
        return await render_page(WS_URL, "https://example.com", 20, content_floor)


async def test_render_ok() -> None:
    """A normal page yields status 'ok' with extracted text, title, and word count."""
    result = await _render(
        FakePage(
            body_text="Main article body with several words here",
            page_title="Article",
            url="https://example.com/article",
        )
    )

    assert result["status"] == "ok"
    assert result["text"] == "Main article body with several words here"
    assert result["title"] == "Article"
    assert result["final_url"] == "https://example.com/article"
    assert result["word_count"] == 7


async def test_render_empty() -> None:
    """A page with no text yields status 'empty' and a zero word count."""
    result = await _render(FakePage(body_text=""))

    assert result["status"] == "empty"
    assert result["word_count"] == 0


async def test_render_error_is_structured_not_raised() -> None:
    """A connect failure returns a structured error rather than raising (ADR 0003)."""
    result = await _render(
        FakePage(), connect_error=RuntimeError("server down")
    )

    assert result["status"] == "error"
    assert "server down" in result["error"]
    assert result["word_count"] == 0


async def test_render_keeps_partial_on_timeout_above_floor() -> None:
    """A navigation timeout with content above the floor is kept as 'ok' (ADR 0003)."""
    body = " ".join(f"word{i}" for i in range(60))  # 60 words, floor is 50
    result = await _render(
        FakePage(body_text=body, goto_error=PlaywrightTimeoutError("timeout")),
        content_floor=50,
    )

    assert result["status"] == "ok"
    assert result["word_count"] == 60
    assert result["text"] == body


async def test_render_timeout_below_floor_is_empty() -> None:
    """A navigation timeout with content below the floor is 'empty', not 'ok'."""
    result = await _render(
        FakePage(
            body_text="only a few words",
            goto_error=PlaywrightTimeoutError("timeout"),
        ),
        content_floor=50,
    )

    assert result["status"] == "empty"
    assert result["word_count"] == 4
