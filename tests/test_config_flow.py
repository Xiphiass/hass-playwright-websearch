"""Test the Playwright Web Search config and options flows."""

from __future__ import annotations

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.playwright_websearch.const import (
    CONF_NUM_RESULTS,
    CONF_PLAYWRIGHT_WS_URL,
    CONF_RENDER_TIMEOUT,
    CONF_SEARXNG_URL,
    DEFAULT_NUM_RESULTS,
    DEFAULT_RENDER_TIMEOUT,
    DOMAIN,
)


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """The form is shown and submitting endpoints creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SEARXNG_URL: "http://searxng.local",
            CONF_PLAYWRIGHT_WS_URL: "ws://playwright.local:3000",
        },
    )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_SEARXNG_URL: "http://searxng.local",
        CONF_PLAYWRIGHT_WS_URL: "ws://playwright.local:3000",
    }


async def test_single_instance_only(hass: HomeAssistant) -> None:
    """A second config flow aborts (one entry owns the llm.API registration)."""
    MockConfigEntry(domain=DOMAIN, data={}).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is data_entry_flow.FlowResultType.ABORT


async def test_options_flow_stores_tunables(hass: HomeAssistant) -> None:
    """The options flow shows defaults and stores updated tunables."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SEARXNG_URL: "http://searxng.local",
            CONF_PLAYWRIGHT_WS_URL: "ws://playwright.local:3000",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"

    # Defaults are rendered when no options are set yet.
    schema_defaults = {
        key.schema: key.default() for key in result["data_schema"].schema
    }
    assert schema_defaults[CONF_NUM_RESULTS] == DEFAULT_NUM_RESULTS
    assert schema_defaults[CONF_RENDER_TIMEOUT] == DEFAULT_RENDER_TIMEOUT

    user_input = {
        CONF_NUM_RESULTS: 3,
        CONF_RENDER_TIMEOUT: 30,
        "per_result_cap": 1500,
        "total_ceiling": 6000,
        "full_page_cap": 15000,
        "concurrency": 2,
        "content_floor": 40,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NUM_RESULTS] == 3
    assert entry.options[CONF_RENDER_TIMEOUT] == 30
