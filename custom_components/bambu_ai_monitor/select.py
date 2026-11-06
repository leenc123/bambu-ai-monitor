"""Select entities for Bambu AI Print Monitor."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .const import (
    CONF_ANALYSIS_INTERVAL,
    DEFAULT_ANALYSIS_INTERVAL,
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
_LABEL_TO_INTERVAL = {label: seconds for seconds, label in INTERVAL_OPTIONS.items()}


def _setup_selects(coordinator: BambuAICoordinator) -> list[BambuAIBaseEntity]:
    """Return select entities."""
    return [
        BambuAnalysisIntervalSelect(coordinator),
    ]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up select entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_setup_selects(coordinator))


class BambuAnalysisIntervalSelect(BambuAIBaseEntity, SelectEntity):
    """Select for analysis interval."""

    _attr_translation_key = "analysis_interval"
    _attr_name = "分析间隔"
    _attr_icon = "mdi:timer"

    @property
    def current_option(self) -> str:
        """Return the current interval label."""
        interval = self.coordinator.config_entry.options.get(
            CONF_ANALYSIS_INTERVAL, DEFAULT_ANALYSIS_INTERVAL
        )
        try:
            return INTERVAL_OPTIONS.get(int(interval), str(interval))
        except (TypeError, ValueError):
            return str(interval)

    @property
    def options(self) -> list[str]:
        """Return available interval labels."""
        return list(INTERVAL_OPTIONS.values())

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        interval = _LABEL_TO_INTERVAL.get(option)
        if interval is None:
            return
        options = dict(self.coordinator.config_entry.options)
        options[CONF_ANALYSIS_INTERVAL] = interval
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry, options=options
        )
        self.async_write_ha_state()
