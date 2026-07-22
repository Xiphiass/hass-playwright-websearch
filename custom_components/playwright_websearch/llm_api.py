"""LLM API and tools exposed to the conversation agent.

Registers a user-selectable :class:`llm.API` that currently exposes the ``open_url``
tool (the issue #2 tracer bullet). ``search_web`` and the rest of the pipeline land in
later tickets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, llm
from homeassistant.util.json import JsonObjectType

from .const import CONF_PLAYWRIGHT_WS_URL, CONF_RENDER_TIMEOUT, DEFAULT_RENDER_TIMEOUT
from .render import render_page

API_PROMPT = (
    "Use open_url to fetch the readable text of a web page. The page is rendered in a "
    "real browser (JavaScript executed) before its text is returned, so it works on "
    "modern single-page-app sites that a plain HTTP fetch cannot read."
)

OPEN_URL_DESCRIPTION = (
    "Open a web page and return its rendered readable text. Renders the page in a real "
    "browser so JavaScript-heavy pages return real content, not an empty shell."
)


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

        result = await render_page(ws_url, url, timeout)

        if result["status"] == "error":
            return {"error": result.get("error", "render failed")}

        return {
            "url": result["final_url"],
            "title": result["title"],
            "text": result["text"],
        }


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
            tools=[OpenUrlTool(self.entry)],
        )
