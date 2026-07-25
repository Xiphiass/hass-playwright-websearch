"""Config and options flow for Playwright Web Search."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_CONCURRENCY,
    CONF_CONTENT_FLOOR,
    CONF_FULL_PAGE_CAP,
    CONF_NUM_RESULTS,
    CONF_PER_RESULT_CAP,
    CONF_PLAYWRIGHT_WS_URL,
    CONF_RENDER_TIMEOUT,
    CONF_SEARXNG_URL,
    CONF_SNIPPET_CEILING,
    CONF_TOTAL_CEILING,
    DEFAULT_CONCURRENCY,
    DEFAULT_CONTENT_FLOOR,
    DEFAULT_FULL_PAGE_CAP,
    DEFAULT_NUM_RESULTS,
    DEFAULT_PER_RESULT_CAP,
    DEFAULT_RENDER_TIMEOUT,
    DEFAULT_SNIPPET_CEILING,
    DEFAULT_TOTAL_CEILING,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SEARXNG_URL): str,
        vol.Required(CONF_PLAYWRIGHT_WS_URL): str,
    }
)


def _options_schema(options: dict[str, Any]) -> vol.Schema:
    """Build the options schema with current values as defaults."""
    return vol.Schema(
        {
            vol.Required(
                CONF_NUM_RESULTS,
                default=options.get(CONF_NUM_RESULTS, DEFAULT_NUM_RESULTS),
            ): vol.All(int, vol.Range(min=1)),
            vol.Required(
                CONF_RENDER_TIMEOUT,
                default=options.get(CONF_RENDER_TIMEOUT, DEFAULT_RENDER_TIMEOUT),
            ): vol.All(int, vol.Range(min=1)),
            vol.Required(
                CONF_PER_RESULT_CAP,
                default=options.get(CONF_PER_RESULT_CAP, DEFAULT_PER_RESULT_CAP),
            ): vol.All(int, vol.Range(min=1)),
            vol.Required(
                CONF_TOTAL_CEILING,
                default=options.get(CONF_TOTAL_CEILING, DEFAULT_TOTAL_CEILING),
            ): vol.All(int, vol.Range(min=1)),
            vol.Required(
                CONF_FULL_PAGE_CAP,
                default=options.get(CONF_FULL_PAGE_CAP, DEFAULT_FULL_PAGE_CAP),
            ): vol.All(int, vol.Range(min=1)),
            vol.Required(
                CONF_CONCURRENCY,
                default=options.get(CONF_CONCURRENCY, DEFAULT_CONCURRENCY),
            ): vol.All(int, vol.Range(min=1)),
            vol.Required(
                CONF_CONTENT_FLOOR,
                default=options.get(CONF_CONTENT_FLOOR, DEFAULT_CONTENT_FLOOR),
            ): vol.All(int, vol.Range(min=0)),
            vol.Required(
                CONF_SNIPPET_CEILING,
                default=options.get(CONF_SNIPPET_CEILING, DEFAULT_SNIPPET_CEILING),
            ): vol.All(int, vol.Range(min=0)),
        }
    )


class PlaywrightWebSearchConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Playwright Web Search."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: capture connection endpoints."""
        # A single config entry owns the llm.API registration (id == DOMAIN).
        self._async_abort_entries_match()

        if user_input is not None:
            return self.async_create_entry(
                title="Playwright Web Search", data=user_input
            )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> PlaywrightWebSearchOptionsFlow:
        """Return the options flow handler."""
        return PlaywrightWebSearchOptionsFlow()


class PlaywrightWebSearchOptionsFlow(OptionsFlow):
    """Handle tunable defaults via the options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the tunable options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(dict(self.config_entry.options)),
        )