"""SSRF protection tests through the faked DNS + Playwright boundaries (ADR 0004).

The DNS seam (``ssrf._resolve``) is patched per test to inject the IP a hostname
resolves to — including the rebinding case where a benign hostname resolves to a private
address. No real DNS and no real Chromium are ever hit.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.playwright_websearch.const import (
    CONF_PLAYWRIGHT_WS_URL,
    CONF_SEARXNG_URL,
    DOMAIN,
)
from custom_components.playwright_websearch.llm_api import OpenUrlTool, SearchWebTool

from .conftest import (
    FakePage,
    fake_searxng_response,
    make_resolver,
    make_routing_playwright,
)

SEARXNG_URL = "http://searxng.local"
WS_URL = "ws://playwright.local:3000"
SEARCH_ENDPOINT = f"{SEARXNG_URL}/search"

_RESOLVE_PATH = "custom_components.playwright_websearch.ssrf._resolve"
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


def _open_url_input(url: str) -> llm.ToolInput:
    return llm.ToolInput(tool_name="open_url", tool_args={"url": url})


def _search_input(query: str) -> llm.ToolInput:
    return llm.ToolInput(tool_name="search_web", tool_args={"query": query})


def _llm_context() -> llm.LLMContext:
    return llm.LLMContext(
        platform="test",
        context=None,
        language="en",
        assistant="conversation",
        device_id=None,
    )


@pytest.mark.parametrize(
    "blocked_ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # RFC1918
        "192.168.1.10",  # RFC1918
        "172.16.0.1",  # RFC1918
        "169.254.169.254",  # link-local cloud metadata endpoint
        "fc00::1",  # IPv6 ULA
        "::1",  # IPv6 loopback
    ],
)
async def test_open_url_refuses_private_target(
    hass: HomeAssistant, patch_playwright, blocked_ip: str
) -> None:
    """open_url against a host resolving to a private IP is refused, never connecting."""
    with patch(_RESOLVE_PATH, new=make_resolver(default=[blocked_ip])):
        result = await OpenUrlTool(_entry()).async_call(
            hass, _open_url_input("https://evil.example/page"), _llm_context()
        )

    assert "error" in result
    assert blocked_ip in result["error"]
    # Refused before navigation: the browser was never contacted.
    assert patch_playwright.connect_calls == []


async def test_open_url_rebinding_resolution_is_refused(
    hass: HomeAssistant, patch_playwright
) -> None:
    """A benign hostname that resolves to a private IP is refused (post-resolution)."""
    with patch(
        _RESOLVE_PATH,
        new=make_resolver({"totally-legit.example": ["10.1.2.3"]}),
    ):
        result = await OpenUrlTool(_entry()).async_call(
            hass, _open_url_input("https://totally-legit.example/x"), _llm_context()
        )

    assert "error" in result
    assert "10.1.2.3" in result["error"]
    assert patch_playwright.connect_calls == []


async def test_open_url_public_target_renders(
    hass: HomeAssistant, patch_playwright
) -> None:
    """A public-resolving target renders normally (the default resolver case)."""
    patch_playwright.page = FakePage(
        body_text="Public content", page_title="Public", url="https://ok.example/"
    )

    result = await OpenUrlTool(_entry()).async_call(
        hass, _open_url_input("https://ok.example/"), _llm_context()
    )

    assert result["text"] == "Public content"
    assert patch_playwright.connect_calls == [WS_URL]


async def test_open_url_configured_endpoint_is_exempt(
    hass: HomeAssistant, patch_playwright
) -> None:
    """The configured SearXNG host renders even though it resolves to a private IP."""
    patch_playwright.page = FakePage(body_text="Internal dashboard")
    # Resolver would block this IP, but the trusted host is exempt and never resolved.
    with patch(_RESOLVE_PATH, new=make_resolver(default=["10.0.0.5"])):
        result = await OpenUrlTool(_entry()).async_call(
            hass, _open_url_input("http://searxng.local/status"), _llm_context()
        )

    assert result["text"] == "Internal dashboard"
    assert patch_playwright.connect_calls == [WS_URL]


async def test_open_url_unresolvable_host_is_refused(
    hass: HomeAssistant, patch_playwright
) -> None:
    """A host that fails to resolve is refused with a structured error."""

    async def _boom(host: str) -> list[str]:
        raise OSError("name or service not known")

    with patch(_RESOLVE_PATH, new=_boom):
        result = await OpenUrlTool(_entry()).async_call(
            hass, _open_url_input("https://nx.example/"), _llm_context()
        )

    assert "error" in result
    assert patch_playwright.connect_calls == []


async def test_search_web_private_result_falls_back_to_snippet(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A result URL resolving to a private IP falls back to its SearXNG snippet."""
    results = [
        {"url": "https://public.example/0", "title": "R0", "content": "Snippet 0"},
        {"url": "https://internal.example/1", "title": "R1", "content": "Snippet 1"},
    ]
    aioclient_mock.get(SEARCH_ENDPOINT, json=fake_searxng_response(results))

    routes = {
        results[0]["url"]: FakePage(body_text="Rendered body 0"),
        results[1]["url"]: FakePage(body_text="Rendered body 1"),
    }
    factory, _bt = make_routing_playwright(routes)

    resolver = make_resolver({"internal.example": ["192.168.0.9"]})
    with patch(_RENDER_PATH, new=factory), patch(_RESOLVE_PATH, new=resolver):
        out = await SearchWebTool(_entry()).async_call(
            hass, _search_input("cats"), _llm_context()
        )

    entries = out["results"]
    assert entries[0]["source"] == "rendered"
    assert entries[0]["text"] == "Rendered body 0"
    # The private result was refused before render and fell back to its snippet.
    assert entries[1]["source"] == "snippet"
    assert entries[1]["text"] == "Snippet 1"
    assert entries[1]["note"]
