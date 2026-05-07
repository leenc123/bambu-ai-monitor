"""Binary sensor entities for Bambu AI Print Monitor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import DOMAIN
from .coordinator import BambuAICoordinator
from .entity import BambuAIBaseEntity


def _setup_binary_sensors(coordinator: BambuAICoordinator) -> list[BambuAIBaseEntity]:
    """Return binary sensor entities."""
    return [
        BambuAnomalyDetectedBinarySensor(coordinator),
        BambuPrinterOnlineBinarySensor(coordinator),
    ]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up binary sensor entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_setup_binary_sensors(coordinator))


class BambuAnomalyDetectedBinarySensor(BambuAIBaseEntity, BinarySensorEntity):
    """Binary sensor for anomaly detection status."""

    _attr_translation_key = "anomaly_detected"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert"

    @property
    def is_on(self) -> bool:
        """Return True if an anomaly is detected."""
        return self.coordinator.data.anomaly_detected


class BambuPrinterOnlineBinarySensor(BambuAIBaseEntity, BinarySensorEntity):
    """Binary sensor for printer online status."""

    _attr_translation_key = "printer_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:printer-3d"

    @property
    def is_on(self) -> bool:
        """Return True if printer is online."""
        return self.coordinator.data.printer_online
