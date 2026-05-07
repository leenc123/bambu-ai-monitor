"""The Bambu AI Print Monitor integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN,
    SERVICE_ANALYZE_NOW,
    SERVICE_SET_ANALYSIS_INTERVAL,
)
from .coordinator import BambuAICoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    "sensor",
    "binary_sensor",
    "button",
    "switch",
    "select",
    "number",
]

type BambuAIConfigEntry = ConfigEntry[BambuAICoordinator]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Bambu AI Print Monitor component."""

    async def handle_analyze_now(call: ServiceCall) -> None:
        """Handle the analyze_now service call."""
        entry_id = call.data.get("entry_id")
        if entry_id:
            coordinator = hass.data[DOMAIN].get(entry_id)
            if coordinator:
                await coordinator.async_analyze_now()
        else:
            for coordinator in hass.data[DOMAIN].values():
                await coordinator.async_analyze_now()

    async def handle_set_analysis_interval(call: ServiceCall) -> None:
        """Handle the set_analysis_interval service call."""
        entry_id = call.data.get("entry_id")
        interval = call.data["interval"]
        if entry_id:
            coordinator = hass.data[DOMAIN].get(entry_id)
            if coordinator:
                await coordinator.async_set_analysis_interval(interval)
        else:
            for coordinator in hass.data[DOMAIN].values():
                await coordinator.async_set_analysis_interval(interval)

    hass.services.async_register(
        DOMAIN, SERVICE_ANALYZE_NOW, handle_analyze_now
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_ANALYSIS_INTERVAL, handle_set_analysis_interval
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: BambuAIConfigEntry) -> bool:
    """Set up Bambu AI Print Monitor from a config entry."""
    coordinator = BambuAICoordinator(hass, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.error("Setup failed for entry %s: %s", entry.entry_id, err, exc_info=True)
        raise ConfigEntryNotReady(f"Failed to connect to printer: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        _LOGGER.error("Failed to set up platforms for %s", entry.entry_id, exc_info=True)
        await coordinator.async_cleanup()
        hass.data[DOMAIN].pop(entry.entry_id)
        raise ConfigEntryNotReady("Failed to set up entities") from None

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BambuAIConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_cleanup()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: BambuAIConfigEntry) -> None:
    """Reload a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
