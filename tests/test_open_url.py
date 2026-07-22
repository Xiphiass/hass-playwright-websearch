"""Test the open_url tool end-to-end through the faked Playwright boundary."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.playwright_websearch.const import (
    CONF_FULL_PAGE_CAP,
    CONF_PLAYWRIGHT_WS_URL,
    CONF_SEARXNG_URL,
    DOMAIN,
)
from custom_components.playwright_websearch.llm_api import OpenUrlTool

from .conftest import FakePage, make_async_playwright


def _entry(options: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SEARXNG_URL: "http://searxng.local",
            CONF_PLAYWRIGHT_WS_URL: "ws://playwright.local:3000",
        },
        options=options or {},
    )


def _tool_input(url: str) -> llm.ToolInput:
    return llm.ToolInput(tool_name="open_url", tool_args={"url": url})


def _llm_context() -> llm.LLMContext:
    return llm.LLMContext(
        platform="test",
        context=None,
        language="en",
        assistant="conversation",
        device_id=None,
    )


async def test_open_url_returns_rendered_text(
    hass: HomeAssistant, patch_playwright
) -> None:
    """open_url returns the page's rendered text (the acceptance criterion)."""
    patch_playwright.page = FakePage(
        body_text="Hello from a JS-rendered SPA",
        page_title="SPA Page",
        url="https://spa.example/article",
    )
    # FakeBrowser needs the same page instance the browser type hands out.
    entry = _entry()
    tool = OpenUrlTool(entry)

    result = await tool.async_call(
        hass, _tool_input("https://spa.example/article"), _llm_context()
    )

    assert result["text"] == "Hello from a JS-rendered SPA"
    assert result["title"] == "SPA Page"
    assert result["url"] == "https://spa.example/article"
    assert patch_playwright.connect_calls == ["ws://playwright.local:3000"]
    # Connect-per-call: the browser was torn down after use.
    assert patch_playwright.browsers[0].closed is True


async def test_open_url_truncates_to_full_page_cap_on_paragraph_boundary(
    hass: HomeAssistant, patch_playwright
) -> None:
    """open_url truncates to the full-page cap on a paragraph boundary."""
    patch_playwright.page = FakePage(
        body_text="First para kept.\n\n" + ("x" * 500),
        page_title="Long Page",
        url="https://example.com/long",
    )
    tool = OpenUrlTool(_entry({CONF_FULL_PAGE_CAP: 30}))

    result = await tool.async_call(
        hass, _tool_input("https://example.com/long"), _llm_context()
    )

    assert result["text"] == "First para kept."


async def test_open_url_under_cap_returns_full_text(
    hass: HomeAssistant, patch_playwright
) -> None:
    """A page shorter than the full-page cap is returned unchanged."""
    body = "Short enough to fit under the cap."
    patch_playwright.page = FakePage(
        body_text=body,
        page_title="Short Page",
        url="https://example.com/short",
    )
    tool = OpenUrlTool(_entry({CONF_FULL_PAGE_CAP: 20000}))

    result = await tool.async_call(
        hass, _tool_input("https://example.com/short"), _llm_context()
    )

    assert result["text"] == body


async def test_open_url_error_is_structured_not_raised(hass: HomeAssistant) -> None:
    """A connect failure returns a structured error, not an exception (ADR 0003)."""
    factory, _bt = make_async_playwright(
        FakePage(), connect_error=RuntimeError("server down")
    )
    entry = _entry()
    tool = OpenUrlTool(entry)

    with patch(
        "custom_components.playwright_websearch.render.async_playwright",
        new=factory,
    ):
        result = await tool.async_call(
            hass, _tool_input("https://example.com"), _llm_context()
        )

    assert "error" in result
    assert "server down" in result["error"]


async def test_open_url_survives_server_restart_between_calls(
    hass: HomeAssistant, patch_playwright
) -> None:
    """Two sequential calls each connect fresh and succeed (ADR 0001 lifecycle)."""
    entry = _entry()
    tool = OpenUrlTool(entry)

    first = await tool.async_call(
        hass, _tool_input("https://example.com/1"), _llm_context()
    )
    second = await tool.async_call(
        hass, _tool_input("https://example.com/2"), _llm_context()
    )

    assert first["text"] == second["text"]
    # A fresh connection was established for each call and each was closed.
    assert len(patch_playwright.connect_calls) == 2
    assert all(browser.closed for browser in patch_playwright.browsers)
