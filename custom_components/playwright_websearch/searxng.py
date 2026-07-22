"""Query the external SearXNG instance for result URLs and Snippets.

This is the SearXNG seam, mirroring how :mod:`render` is the render seam: one async
entry point that callers (the ``search_web`` tool) use, and the single place tests fake
the metasearch HTTP call. It uses Home Assistant's shared aiohttp session so tests can
intercept the request via ``aioclient_mock``.

SearXNG is queried, not page-fetched — this is the metasearch call, not an HTTP page
render fallback (ADR 0005 forbids the latter, not this).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# Bound the metasearch HTTP call so a slow/hung SearXNG never wedges a search.
_SEARCH_TIMEOUT = 10


async def async_search(
    hass: HomeAssistant, base_url: str, query: str, num_results: int
) -> list[dict[str, str]]:
    """Query SearXNG's JSON API and return up to ``num_results`` result dicts.

    Each returned dict carries ``url``, ``title``, and ``content`` (the Snippet).
    Raises on transport/HTTP/parse errors so the caller can surface a structured error
    (there is no HTTP page-fetch fallback tier — ADR 0005).
    """
    session = async_get_clientsession(hass)
    search_url = f"{base_url.rstrip('/')}/search"
    params = {"q": query, "format": "json"}

    async with asyncio.timeout(_SEARCH_TIMEOUT):
        async with session.get(search_url, params=params) as response:
            response.raise_for_status()
            payload: dict[str, Any] = await response.json()

    results: list[dict[str, str]] = []
    for item in payload.get("results", [])[:num_results]:
        results.append(
            {
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "content": item.get("content", ""),
            }
        )
    _LOGGER.debug("SearXNG returned %d results for %r", len(results), query)
    return results
