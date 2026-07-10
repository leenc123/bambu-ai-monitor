"""Number entities for Bambu AI Print Monitor."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)

from .const import (
    CONF_CONFIDENCE_THRESHOLD,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DOMAIN,
)
from .coordinator import BambuAICoordinator
from .entity import BambuAIBaseEntity


def _setup_numbers(coordinator: BambuAICoordinator) -> list[BambuAIBaseEntity]:
    """Return number entities."""
    return [
        BambuConfidenceThresholdNumber(coordinator),
    ]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up number entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_setup_numbers(coordinator))


class BambuConfidenceThresholdNumber(BambuAIBaseEntity, NumberEntity):
    """Number input for AI confidence threshold."""

    _attr_translation_key = "confidence_threshold"
    _attr_name = "置信度阈值"
    _attr_native_min_value = 0.1
    _attr_native_max_value = 1.0
    _attr_native_step = 0.05
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:percent"

    @property
    def native_value(self) -> float:
        """Return the current confidence threshold."""
        return self.coordinator.config_entry.options.get(
            CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD
        )

    async def async_set_native_value(self, value: float) -> None:
        """Update the confidence threshold."""
        options = dict(self.coordinator.config_entry.options)
        options[CONF_CONFIDENCE_THRESHOLD] = value
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry, options=options
        )
        self.coordinator._confidence_threshold = value
        self.async_write_ha_state()
