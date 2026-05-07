"""Switch entities for Bambu AI Print Monitor."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription

from .const import (
    CONF_AUTO_PAUSE,
    DEFAULT_AUTO_PAUSE,
    DOMAIN,
)
from .coordinator import BambuAICoordinator
from .entity import BambuAIBaseEntity


def _setup_switches(coordinator: BambuAICoordinator) -> list[BambuAIBaseEntity]:
    """Return switch entities."""
    return [
        BambuAutoPauseSwitch(coordinator),
    ]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up switch entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_setup_switches(coordinator))


class BambuAutoPauseSwitch(BambuAIBaseEntity, SwitchEntity):
    """Switch to enable/disable auto-pause on anomaly detection."""

    _attr_translation_key = "auto_pause"
    _attr_icon = "mdi:robot"

    @property
    def is_on(self) -> bool:
        """Return True if auto-pause is enabled."""
        return self.coordinator._auto_pause_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on auto-pause."""
        options = dict(self.coordinator.config_entry.options)
        options[CONF_AUTO_PAUSE] = True
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry, options=options
        )
        self.coordinator._auto_pause_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off auto-pause."""
        options = dict(self.coordinator.config_entry.options)
        options[CONF_AUTO_PAUSE] = False
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry, options=options
        )
        self.coordinator._auto_pause_enabled = False
        self.async_write_ha_state()
