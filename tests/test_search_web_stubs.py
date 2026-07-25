"""Tests for search_web stub entries when the total ceiling is exhausted.

Verifies the behavior introduced in issue #10: over-ceiling results appear as
lightweight stubs (url + title, source: "stub") instead of being silently dropped.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.playwright_websearch.const import (
    CONF_NUM_RESULTS,
    CONF_PER_RESULT_CAP,
    CONF_PLAYWRIGHT_WS_URL,
    CONF_SEARXNG_URL,
    CONF_SNIPPET_CEILING,
    CONF_TOTAL_CEILING,
    DOMAIN,
)
from custom_components.playwright_websearch.llm_api import SearchWebTool

from .conftest import FakePage, fake_searxng_response, make_routing_playwright

SEARXNG_URL = "http://searxng.local"
WS_URL = "ws://playwright.local:3000"
SEARCH_ENDPOINT = f"{SEARXNG_URL}/search"

_RENDER_PATH = "custom_components.playwright_websearch.render.async_playwright"


def _entry(options: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SEARXNG_URL: SEARXNG_URL,
            CONF_PLAYWRIGHT_WS_URL: WS_URL,
        },
        options=options or {},
    )


def _tool_input(query: str) -> llm.ToolInput:
    return llm.ToolInput(tool_name="search_web", tool_args={"query": query})


def _llm_context() -> llm.LLMContext:
    return llm.LLMContext(
        platform="test",
        context=None,
        language="en",
        assistant="conversation",
        device_id=None,
    )


def _searxng_results(n: int) -> list[dict[str, str]]:
    return [
        {
            "url": f"https://example.com/{i}",
            "title": f"Result {i}",
            "content": f"Snippet {i}",
        }
        for i in range(n)
    ]


async def test_over_ceiling_emits_stubs(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When the total ceiling is exhausted, later results appear as stubs."""
    results = _searxng_results(3)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    big = "x" * 200  # big enough to exhaust a small ceiling
    routes = {r["url"]: FakePage(body_text=big) for r in results}
    factory, _bt = make_routing_playwright(routes)

    # Ceiling of 100: first result (200 chars, truncated to 100) consumes it all.
    tool = SearchWebTool(
        _entry({CONF_TOTAL_CEILING: 100, CONF_PER_RESULT_CAP: 200})
    )
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    entries = out["results"]
    # First result is rendered (text within ceiling).
    assert entries[0]["source"] == "rendered"
    assert len(entries[0]["text"]) > 0
    # Remaining results are stubs.
    assert entries[1]["source"] == "stub"
    assert entries[1]["text"] == ""
    assert entries[1]["note"] == "total ceiling exhausted; use open_url to read full page"
    assert entries[2]["source"] == "stub"
    assert entries[2]["text"] == ""
    # All URLs and titles are preserved.
    assert entries[1]["url"] == "https://example.com/1"
    assert entries[1]["title"] == "Result 1"


async def test_stub_tier_bounded_by_snippet_ceiling(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When the snippet ceiling is also exhausted, stubs are dropped entirely."""
    results = _searxng_results(5)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    big = "x" * 200
    routes = {r["url"]: FakePage(body_text=big) for r in results}
    factory, _bt = make_routing_playwright(routes)

    # Tiny snippet ceiling: only enough room for ~2 stub entries.
    tool = SearchWebTool(
        _entry({
            CONF_TOTAL_CEILING: 100,
            CONF_PER_RESULT_CAP: 200,
            CONF_SNIPPET_CEILING: 30,  # very small
        })
    )
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    entries = out["results"]
    # First result is rendered.
    assert entries[0]["source"] == "rendered"
    # Remaining results are stubs until snippet ceiling runs out.
    stub_count = sum(1 for e in entries if e["source"] == "stub")
    assert stub_count < 4  # not all 4 over-ceiling results made it through


async def test_stub_with_snippet_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A result that falls back to snippet AND is past the ceiling gets source: 'stub'."""
    results = _searxng_results(2)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    # Result 0 is big (consumes ceiling). Result 1 would render fine but is past ceiling.
    big = "x" * 200
    routes = {
        results[0]["url"]: FakePage(body_text=big),
        results[1]["url"]: FakePage(body_text="Good content"),
    }
    factory, _bt = make_routing_playwright(routes)

    tool = SearchWebTool(
        _entry({CONF_TOTAL_CEILING: 100, CONF_PER_RESULT_CAP: 200})
    )
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    entries = out["results"]
    assert entries[0]["source"] == "rendered"
    assert entries[1]["source"] == "stub"  # past ceiling, so stub regardless of render quality


async def test_stub_preserves_all_result_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Stub entries carry url and title, matching the original result."""
    results = _searxng_results(3)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    big = "x" * 200
    routes = {r["url"]: FakePage(body_text=big) for r in results}
    factory, _bt = make_routing_playwright(routes)

    tool = SearchWebTool(
        _entry({CONF_TOTAL_CEILING: 100, CONF_PER_RESULT_CAP: 200})
    )
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    for i, entry in enumerate(out["results"]):
        assert entry["url"] == results[i]["url"]
        assert entry["title"] == results[i]["title"]


async def test_no_stubs_when_ceiling_not_exhausted(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When the ceiling is not exhausted, no stub entries are emitted."""
    results = _searxng_results(3)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    small = "hi"  # tiny content, won't exhaust a large ceiling
    routes = {r["url"]: FakePage(body_text=small) for r in results}
    factory, _bt = make_routing_playwright(routes)

    tool = SearchWebTool(
        _entry({CONF_TOTAL_CEILING: 10000, CONF_PER_RESULT_CAP: 200})
    )
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    entries = out["results"]
    assert len(entries) == 3
    for entry in entries:
        assert entry["source"] == "rendered"
        assert "stub" not in entry.get("note", "")