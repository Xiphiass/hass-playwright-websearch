"""The Playwright Web Search integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .const import DOMAIN
from .llm_api import WebSearchAPI

type PlaywrightWebSearchConfigEntry = ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: PlaywrightWebSearchConfigEntry
) -> bool:
    """Set up Playwright Web Search from a config entry."""
    unregister = llm.async_register_api(
        hass,
        WebSearchAPI(
            hass=hass,
            id=DOMAIN,
            name="Playwright Web Search",
            entry=entry,
        ),
    )
    entry.async_on_unload(unregister)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PlaywrightWebSearchConfigEntry
) -> bool:
    """Unload a config entry (registration is torn down via async_on_unload)."""
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: PlaywrightWebSearchConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
