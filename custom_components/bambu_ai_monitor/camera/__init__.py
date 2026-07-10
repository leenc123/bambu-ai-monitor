"""Camera entity for Bambu AI Print Monitor — shows YOLO-annotated snapshot."""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from ..const import (
    CONF_HOST,
    CONF_PRINTER_MODEL,
    CONF_SERIAL,
    DOMAIN,
    MANUFACTURER,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up camera entity."""
    from ..coordinator import BambuAICoordinator
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BambuAICamera(coordinator)])


class BambuAICamera(CoordinatorEntity, Camera):
    """Camera that shows annotated YOLO detection results."""

    _attr_translation_key = "annotated_snapshot"

    def __init__(self, coordinator) -> None:
        """Initialize the camera."""
        super().__init__(coordinator)
        Camera.__init__(self)

        data = coordinator.config_entry.data
        serial = data.get("serial", data[CONF_HOST])
        self._attr_unique_id = f"{serial}_camera"
        self._attr_name = "YOLO 检测画面"

        model = data.get(CONF_PRINTER_MODEL, "Bambu Printer")
        serial = data.get(CONF_SERIAL, data[CONF_HOST])
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=f"Bambu {model}",
            manufacturer=MANUFACTURER,
            model=model,
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the latest annotated image from the coordinator's analysis."""
        annotated = getattr(self.coordinator, "_last_annotated_image", None)
        if annotated:
            return annotated
        # Placeholder when no analysis has run yet
        return None

    @property
    def should_poll(self) -> bool:
        """Camera polls for updates."""
        return True
