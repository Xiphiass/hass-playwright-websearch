"""LLM API and tools exposed to the conversation agent.

Registers a user-selectable :class:`llm.API` that currently exposes the ``open_url``
tool (the issue #2 tracer bullet). ``search_web`` and the rest of the pipeline land in
later tickets.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, llm
from homeassistant.util.json import JsonObjectType

from .budget import truncate_to_cap
from .const import (
    CONF_CONCURRENCY,
    CONF_CONTENT_FLOOR,
    CONF_FULL_PAGE_CAP,
    CONF_NUM_RESULTS,
    CONF_PER_RESULT_CAP,
    CONF_PLAYWRIGHT_WS_URL,
    CONF_RENDER_TIMEOUT,
    CONF_SEARXNG_URL,
    CONF_TOTAL_CEILING,
    DEFAULT_CONCURRENCY,
    DEFAULT_CONTENT_FLOOR,
    DEFAULT_FULL_PAGE_CAP,
    DEFAULT_NUM_RESULTS,
    DEFAULT_PER_RESULT_CAP,
    DEFAULT_RENDER_TIMEOUT,
    DEFAULT_TOTAL_CEILING,
)
from .render import render_page
from .searxng import async_search

_LOGGER = logging.getLogger(__name__)

API_PROMPT = (
    "Use search_web to find and read the top web results for a query: it renders each "
    "result page in a real browser and returns a short readable extract per result so "
    "you can judge relevance. Use open_url to read the full text of a single page. Both "
    "render JavaScript, so they work on modern single-page-app sites that a plain HTTP "
    "fetch cannot read."
)

OPEN_URL_DESCRIPTION = (
    "Open a web page and return its rendered readable text. Renders the page in a real "
    "browser so JavaScript-heavy pages return real content, not an empty shell."
)

SEARCH_WEB_DESCRIPTION = (
    "Search the web for a query and return a short readable extract of each top result. "
    "Each result page is rendered in a real browser; if a page cannot be rendered, its "
    "search-result snippet is returned instead. Use open_url to read a result in full."
)

# Note attached to a result that fell back to its SearXNG snippet.
_SNIPPET_NOTE = "render failed; showing search snippet"


class OpenUrlTool(llm.Tool):
    """Render a single URL and return its text."""

    name = "open_url"
    description = OPEN_URL_DESCRIPTION
    parameters = vol.Schema({vol.Required("url"): cv.url})

    def __init__(self, entry: ConfigEntry) -> None:
        """Keep a reference to the config entry for runtime config."""
        self._entry = entry

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Render the requested URL and return its text to the LLM."""
        url = tool_input.tool_args["url"]
        ws_url = self._entry.data[CONF_PLAYWRIGHT_WS_URL]
        timeout = self._entry.options.get(
            CONF_RENDER_TIMEOUT, DEFAULT_RENDER_TIMEOUT
        )
        content_floor = self._entry.options.get(
            CONF_CONTENT_FLOOR, DEFAULT_CONTENT_FLOOR
        )
        full_page_cap = self._entry.options.get(
            CONF_FULL_PAGE_CAP, DEFAULT_FULL_PAGE_CAP
        )

        result = await render_page(ws_url, url, timeout, content_floor)

        if result["status"] == "error":
            return {"error": result.get("error", "render failed")}

        return {
            "url": result["final_url"],
            "title": result["title"],
            "text": truncate_to_cap(result["text"], full_page_cap),
        }


class SearchWebTool(llm.Tool):
    """Query SearXNG, render the top results, and return a budgeted extract of each."""

    name = "search_web"
    description = SEARCH_WEB_DESCRIPTION
    parameters = vol.Schema({vol.Required("query"): cv.string})

    def __init__(self, entry: ConfigEntry) -> None:
        """Keep a reference to the config entry for runtime config."""
        self._entry = entry

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Search, render each result under a semaphore, and budget the output."""
        query = tool_input.tool_args["query"]
        searxng_url = self._entry.data[CONF_SEARXNG_URL]
        ws_url = self._entry.data[CONF_PLAYWRIGHT_WS_URL]
        options = self._entry.options
        num_results = options.get(CONF_NUM_RESULTS, DEFAULT_NUM_RESULTS)
        timeout = options.get(CONF_RENDER_TIMEOUT, DEFAULT_RENDER_TIMEOUT)
        per_result_cap = options.get(CONF_PER_RESULT_CAP, DEFAULT_PER_RESULT_CAP)
        total_ceiling = options.get(CONF_TOTAL_CEILING, DEFAULT_TOTAL_CEILING)
        concurrency = options.get(CONF_CONCURRENCY, DEFAULT_CONCURRENCY)
        content_floor = options.get(CONF_CONTENT_FLOOR, DEFAULT_CONTENT_FLOOR)

        try:
            results = await async_search(hass, searxng_url, query, num_results)
        except Exception as err:  # noqa: BLE001 - surface as a structured error
            _LOGGER.debug("SearXNG query failed for %r: %s", query, err)
            return {"error": f"search failed: {err}"}

        if not results:
            return {"query": query, "results": []}

        # Render every result page concurrently, bounded by the semaphore. render_page
        # never raises (ADR 0003), so gather results map 1:1 to results in order.
        sem = asyncio.Semaphore(concurrency)

        async def _render_one(target_url: str):
            async with sem:
                return await render_page(ws_url, target_url, timeout, content_floor)

        rendered = await asyncio.gather(
            *(_render_one(result["url"]) for result in results)
        )

        # Assemble output in result order, spending the total ceiling as we go. A
        # kept-partial render surfaces as "ok" (ticket #3) and is treated as normal
        # content; error/empty renders fall back to the SearXNG snippet.
        out: list[JsonObjectType] = []
        remaining = total_ceiling
        dropped = 0
        for result, render in zip(results, rendered):
            if remaining <= 0:
                dropped += 1
                continue

            if render["status"] == "ok":
                raw_text = render["text"]
                source = "rendered"
                note = None
            else:
                raw_text = result["content"]
                source = "snippet"
                note = _SNIPPET_NOTE

            text = truncate_to_cap(raw_text, min(per_result_cap, remaining))
            remaining -= len(text)

            entry: JsonObjectType = {
                "url": result["url"],
                "title": result["title"],
                "text": text,
                "source": source,
            }
            if note is not None:
                entry["note"] = note
            out.append(entry)

        if dropped:
            _LOGGER.debug(
                "search_web dropped %d result(s) after hitting the total ceiling",
                dropped,
            )

        return {"query": query, "results": out}


@dataclass(slots=True, kw_only=True)
class WebSearchAPI(llm.API):
    """User-selectable LLM API bundling the Playwright web-search tools."""

    entry: ConfigEntry = field(kw_only=True)

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        """Return the API instance with its tools."""
        return llm.APIInstance(
            api=self,
            api_prompt=API_PROMPT,
            llm_context=llm_context,
            tools=[OpenUrlTool(self.entry), SearchWebTool(self.entry)],
        )
