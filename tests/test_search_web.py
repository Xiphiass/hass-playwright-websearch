"""End-to-end tests for the ``search_web`` tool through the faked boundaries.

Two seams are combined: ``aioclient_mock`` for the SearXNG HTTP query and the patched
``render.async_playwright`` for per-result rendering. No real Chromium, no real network.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.playwright_websearch.const import (
    CONF_CONCURRENCY,
    CONF_NUM_RESULTS,
    CONF_PER_RESULT_CAP,
    CONF_PLAYWRIGHT_WS_URL,
    CONF_SEARXNG_URL,
    CONF_TOTAL_CEILING,
    DOMAIN,
)
from custom_components.playwright_websearch.llm_api import SearchWebTool
from custom_components.playwright_websearch.pw_client import (
    TimeoutError as PlaywrightTimeoutError,
)

from .conftest import (
    ConcurrencyTracker,
    FakePage,
    fake_searxng_response,
    make_routing_playwright,
)

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


async def test_multi_result_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """search_web queries SearXNG and renders the top N results."""
    results = _searxng_results(3)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    routes = {
        r["url"]: FakePage(body_text=f"Rendered body {i}", page_title=f"Page {i}")
        for i, r in enumerate(results)
    }
    factory, browser_type = make_routing_playwright(routes)

    tool = SearchWebTool(_entry())
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    assert out["query"] == "cats"
    assert len(out["results"]) == 3
    for i, entry in enumerate(out["results"]):
        assert entry["source"] == "rendered"
        assert entry["text"] == f"Rendered body {i}"
        assert "note" not in entry
    # Each result rendered in its own connect-per-call context.
    assert len(browser_type.connect_calls) == 3
    assert all(browser.closed for browser in browser_type.browsers)


async def test_mixed_success_and_snippet_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A result whose render hard-fails falls back to its SearXNG snippet."""
    results = _searxng_results(3)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    routes = {
        results[0]["url"]: FakePage(body_text="Good body 0"),
        # Result 1 hard-fails to render (empty body, no words -> status "empty").
        results[1]["url"]: FakePage(body_text=""),
        results[2]["url"]: FakePage(body_text="Good body 2"),
    }
    factory, _bt = make_routing_playwright(routes)

    tool = SearchWebTool(_entry())
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    entries = out["results"]
    assert entries[0]["source"] == "rendered"
    assert entries[0]["text"] == "Good body 0"
    # The broken page fell back to the snippet, tagged with a note.
    assert entries[1]["source"] == "snippet"
    assert entries[1]["text"] == "Snippet 1"
    assert entries[1]["note"]
    assert entries[2]["source"] == "rendered"
    assert entries[2]["text"] == "Good body 2"


async def test_semaphore_bounds_concurrency(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Concurrent renders within one search are bounded by the semaphore."""
    results = _searxng_results(5)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    tracker = ConcurrencyTracker(hold=0.02)
    routes = {r["url"]: FakePage(body_text=f"Body {i}") for i, r in enumerate(results)}
    factory, _bt = make_routing_playwright(routes, tracker=tracker)

    tool = SearchWebTool(_entry({CONF_CONCURRENCY: 2}))
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    assert len(out["results"]) == 5
    # Never more than the configured concurrency in flight at once.
    assert tracker.max_active == 2


async def test_kept_partial_surfaces_as_rendered(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A kept-partial render (timeout above the floor) is normal rendered content."""
    results = _searxng_results(1)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    body = " ".join(f"word{i}" for i in range(60))  # 60 words, above default floor 50
    routes = {
        results[0]["url"]: FakePage(
            body_text=body, goto_error=PlaywrightTimeoutError("timeout")
        )
    }
    factory, _bt = make_routing_playwright(routes)

    tool = SearchWebTool(_entry())
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    entry = out["results"][0]
    assert entry["source"] == "rendered"
    assert entry["text"] == body


async def test_per_result_cap_truncates_on_paragraph_boundary(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Each result is truncated to the per-result cap on a paragraph boundary."""
    results = _searxng_results(1)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    body = "First para kept.\n\n" + ("x" * 500)
    routes = {results[0]["url"]: FakePage(body_text=body)}
    factory, _bt = make_routing_playwright(routes)

    tool = SearchWebTool(_entry({CONF_PER_RESULT_CAP: 30}))
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    assert out["results"][0]["text"] == "First para kept."


async def test_total_ceiling_drops_later_results(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Once the total ceiling is spent, later results are dropped."""
    results = _searxng_results(3)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    big = "y" * 100
    routes = {r["url"]: FakePage(body_text=big) for r in results}
    factory, _bt = make_routing_playwright(routes)

    # Ceiling of 100 with a per-result cap of 100: the first result consumes it all.
    tool = SearchWebTool(
        _entry({CONF_TOTAL_CEILING: 100, CONF_PER_RESULT_CAP: 100})
    )
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    assert len(out["results"]) == 1


async def test_num_results_limits_query(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Only up to num_results pages are rendered."""
    results = _searxng_results(10)
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    routes = {r["url"]: FakePage(body_text=f"Body {i}") for i, r in enumerate(results)}
    factory, browser_type = make_routing_playwright(routes)

    tool = SearchWebTool(_entry({CONF_NUM_RESULTS: 2}))
    with patch(_RENDER_PATH, new=factory):
        out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    assert len(out["results"]) == 2
    assert len(browser_type.connect_calls) == 2


async def test_searxng_unreachable_returns_structured_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A SearXNG failure returns a structured error, not an exception."""
    aioclient_mock.get(SEARCH_ENDPOINT, exc=Exception("connection refused"))

    tool = SearchWebTool(_entry())
    out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    assert "error" in out
    assert "connection refused" in out["error"]


async def test_no_results_returns_empty_list(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An empty SearXNG result set returns an empty results list, no error."""
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response([]))

    tool = SearchWebTool(_entry())
    out = await tool.async_call(hass, _tool_input("cats"), _llm_context())

    assert out == {"query": "cats", "results": []}
