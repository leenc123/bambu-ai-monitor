"""Select entities for Bambu AI Print Monitor."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.select import SelectEntity

from .const import (
    CONF_ANALYSIS_INTERVAL,
    CONF_ANALYSIS_MODEL,
    DEFAULT_ANALYSIS_INTERVAL,
    DEFAULT_ANALYSIS_MODEL,
    AI_MODELS,
    DOMAIN,
)
from .coordinator import BambuAICoordinator
from .entity import BambuAIBaseEntity

INTERVAL_OPTIONS = {
    30: "30秒",
    60: "1分钟",
    300: "5分钟",
    600: "10分钟",
    1800: "30分钟",
}


def _setup_selects(coordinator: BambuAICoordinator) -> list[BambuAIBaseEntity]:
    """Return select entities."""
    return [
        BambuAnalysisIntervalSelect(coordinator),
        BambuAnalysisModelSelect(coordinator),
    ]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up select entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_setup_selects(coordinator))


class BambuAnalysisIntervalSelect(BambuAIBaseEntity, SelectEntity):
    """Select for analysis interval."""

    _attr_translation_key = "analysis_interval"
    _attr_icon = "mdi:timer"

    @property
    def current_option(self) -> str:
        """Return the current interval."""
        interval = self.coordinator.config_entry.options.get(
            CONF_ANALYSIS_INTERVAL, DEFAULT_ANALYSIS_INTERVAL
        )
        return str(interval)

    @property
    def options(self) -> list[str]:
        """Return available options."""
        return [str(k) for k in INTERVAL_OPTIONS]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        interval = int(option)
        options = dict(self.coordinator.config_entry.options)
        options[CONF_ANALYSIS_INTERVAL] = interval
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry, options=options
        )
        self.coordinator.update_interval = timedelta(seconds=interval)
        self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class BambuAnalysisModelSelect(BambuAIBaseEntity, SelectEntity):
    """Select for AI analysis model."""

    _attr_translation_key = "analysis_model"
    _attr_icon = "mdi:brain"

    @property
    def current_option(self) -> str:
        """Return the current model."""
        return self.coordinator.config_entry.options.get(
            CONF_ANALYSIS_MODEL,
            self.coordinator.config_entry.data.get(
                CONF_ANALYSIS_MODEL, DEFAULT_ANALYSIS_MODEL
            ),
        )

    @property
    def options(self) -> list[str]:
        """Return available models."""
        return list(AI_MODELS.keys())

    async def async_select_option(self, option: str) -> None:
        """Change the selected model."""
        options = dict(self.coordinator.config_entry.options)
        options[CONF_ANALYSIS_MODEL] = option
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry, options=options
        )
        self.async_write_ha_state()
