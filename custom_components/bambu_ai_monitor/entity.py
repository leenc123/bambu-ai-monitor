"""Base entity for Bambu AI Print Monitor."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HOST,
    CONF_PRINTER_MODEL,
    CONF_SERIAL,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import BambuAICoordinator


class BambuAIBaseEntity(CoordinatorEntity[BambuAICoordinator]):
    """Base entity for all Bambu AI Monitor entities."""

    _attr_has_entity_name = True
    _attr_translation_key = ""

    def __init__(
        self,
        coordinator: BambuAICoordinator,
        translation_key: str | None = None,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)

        # Use explicit parameter or fallback to class attribute
        key = translation_key or self._attr_translation_key

        data = coordinator.config_entry.data
        model = data.get(CONF_PRINTER_MODEL, "Bambu Printer")
        serial = data.get(CONF_SERIAL) or data.get(CONF_HOST, "unknown")

        self._attr_unique_id = f"{serial}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=f"Bambu {model}",
            manufacturer=MANUFACTURER,
            model=model,
        )
