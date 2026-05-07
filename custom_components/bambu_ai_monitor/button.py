"""Button entities for Bambu AI Print Monitor."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .const import DOMAIN
from .coordinator import BambuAICoordinator
from .entity import BambuAIBaseEntity


def _setup_buttons(coordinator: BambuAICoordinator) -> list[BambuAIBaseEntity]:
    """Return button entities."""
    return [
        BambuPauseButton(coordinator),
        BambuResumeButton(coordinator),
        BambuStopButton(coordinator),
        BambuAnalyzeNowButton(coordinator),
    ]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up button entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_setup_buttons(coordinator))


class BambuPauseButton(BambuAIBaseEntity, ButtonEntity):
    """Button to pause the current print."""

    _attr_translation_key = "pause_print"
    _attr_icon = "mdi:pause"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_pause_print()


class BambuResumeButton(BambuAIBaseEntity, ButtonEntity):
    """Button to resume a paused print."""

    _attr_translation_key = "resume_print"
    _attr_icon = "mdi:play"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_resume_print()


class BambuStopButton(BambuAIBaseEntity, ButtonEntity):
    """Button to stop the current print."""

    _attr_translation_key = "stop_print"
    _attr_icon = "mdi:stop"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_stop_print()


class BambuAnalyzeNowButton(BambuAIBaseEntity, ButtonEntity):
    """Button to trigger immediate AI analysis."""

    _attr_translation_key = "analyze_now"
    _attr_icon = "mdi:magnify-scan"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_analyze_now()
