"""Button entities for Bambu AI Print Monitor."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN
from .coordinator import BambuAICoordinator
from .entity import BambuAIBaseEntity


def _setup_buttons(coordinator: BambuAICoordinator) -> list[BambuAIBaseEntity]:
    """Return button entities."""
    return [
        BambuAnalyzeNowButton(coordinator),
    ]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up button entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_setup_buttons(coordinator))


class BambuAnalyzeNowButton(BambuAIBaseEntity, ButtonEntity):
    """Button to trigger immediate AI analysis."""

    _attr_translation_key = "analyze_now"
    _attr_name = "立即分析"
    _attr_icon = "mdi:magnify-scan"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_analyze_now()



