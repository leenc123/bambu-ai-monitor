"""Sensor entities for Bambu AI Print Monitor."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)

from .const import ANOMALY_TRANSLATIONS, DOMAIN
from .coordinator import BambuAICoordinator
from .entity import BambuAIBaseEntity


def _setup_sensors(coordinator: BambuAICoordinator) -> list[BambuAIBaseEntity]:
    """Return sensor entities."""
    return [
        BambuPrintStatusSensor(coordinator),
        BambuPrintProgressSensor(coordinator),
        BambuBedTempSensor(coordinator),
        BambuNozzleTempSensor(coordinator),
        BambuRemainingTimeSensor(coordinator),
        BambuLastAnalysisSensor(coordinator),
        BambuAnomalyTypeSensor(coordinator),
        BambuLayerSensor(coordinator),
    ]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up sensor entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_setup_sensors(coordinator))


class BambuPrintStatusSensor(BambuAIBaseEntity, SensorEntity):
    """Sensor for printer status."""

    _attr_translation_key = "print_status"
    _attr_icon = "mdi:printer-3d"

    @property
    def native_value(self) -> str:
        """Return the current printer status."""
        status_map = {
            "idle": "空闲",
            "preparing": "准备中",
            "running": "打印中",
            "paused": "已暂停",
            "finished": "已完成",
            "failed": "已失败",
            "unknown": "未知",
        }
        return status_map.get(self.coordinator.data.printer_status, "未知")


class BambuPrintProgressSensor(BambuAIBaseEntity, SensorEntity):
    """Sensor for print progress percentage."""

    _attr_translation_key = "print_progress"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:progress-clock"

    @property
    def native_value(self) -> float:
        """Return the print progress."""
        return self.coordinator.data.print_progress


class BambuBedTempSensor(BambuAIBaseEntity, SensorEntity):
    """Sensor for bed temperature."""

    _attr_translation_key = "bed_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float:
        """Return the bed temperature."""
        return self.coordinator.data.bed_temperature


class BambuNozzleTempSensor(BambuAIBaseEntity, SensorEntity):
    """Sensor for nozzle temperature."""

    _attr_translation_key = "nozzle_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float:
        """Return the nozzle temperature."""
        return self.coordinator.data.nozzle_temperature


class BambuRemainingTimeSensor(BambuAIBaseEntity, SensorEntity):
    """Sensor for remaining print time."""

    _attr_translation_key = "remaining_time"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-sand"

    @property
    def native_value(self) -> int:
        """Return remaining time in minutes."""
        return self.coordinator.data.remaining_time_min


class BambuLastAnalysisSensor(BambuAIBaseEntity, SensorEntity):
    """Sensor for last AI analysis description."""

    _attr_translation_key = "last_analysis"
    _attr_icon = "mdi:eye-check"

    @property
    def native_value(self) -> str | None:
        """Return the last analysis description."""
        if self.coordinator.data.last_analysis:
            return self.coordinator.data.last_analysis.description
        return None


class BambuAnomalyTypeSensor(BambuAIBaseEntity, SensorEntity):
    """Sensor for detected anomaly type."""

    _attr_translation_key = "anomaly_type"
    _attr_icon = "mdi:alert-circle"

    @property
    def native_value(self) -> str | None:
        """Return the anomaly type in Chinese."""
        if self.coordinator.data.anomaly_type:
            return ANOMALY_TRANSLATIONS.get(
                self.coordinator.data.anomaly_type,
                self.coordinator.data.anomaly_type,
            )
        return None


class BambuLayerSensor(BambuAIBaseEntity, SensorEntity):
    """Sensor for current layer progress."""

    _attr_translation_key = "layer_progress"
    _attr_icon = "mdi:layers"

    @property
    def native_value(self) -> str:
        """Return the current layer / total layers."""
        current = self.coordinator.data.layer_num
        total = self.coordinator.data.total_layer_count
        if total > 0:
            return f"{current}/{total}"
        return f"{current}"
