"""Diagnostics support for Bambu AI Print Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_CODE, CONF_AI_API_KEY, CONF_SERIAL, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    config_data = {**entry.data}
    if CONF_ACCESS_CODE in config_data:
        config_data[CONF_ACCESS_CODE] = REDACTED
    if CONF_AI_API_KEY in config_data:
        config_data[CONF_AI_API_KEY] = REDACTED
    if CONF_SERIAL in config_data:
        config_data[CONF_SERIAL] = REDACTED

    return {
        "config": config_data,
        "options": {**entry.options},
        "coordinator_data": {
            "printer_status": coordinator.data.printer_status if coordinator.data else None,
            "print_progress": coordinator.data.print_progress if coordinator.data else None,
            "anomaly_detected": coordinator.data.anomaly_detected if coordinator.data else None,
            "last_analysis_time": coordinator.data.last_analysis_time if coordinator.data else None,
            "last_error": coordinator.data.last_error if coordinator.data else None,
            "printer_online": coordinator.data.printer_online if coordinator.data else None,
        },
    }
