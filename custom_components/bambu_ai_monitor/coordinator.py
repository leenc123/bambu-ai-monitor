"""DataUpdateCoordinator for Bambu AI Print Monitor."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.persistent_notification import async_create

from .const import (
    CONF_ANALYSIS_INTERVAL,
    CONF_ANALYSIS_MODEL,
    CONF_AUTO_PAUSE,
    CONF_CONFIDENCE_THRESHOLD,
    CONF_CONSECUTIVE_DETECTIONS,
    CONF_AI_API_KEY,
    CONF_HOST,
    CONF_ACCESS_CODE,
    CONF_CAMERA_PORT,
    CONF_PRINTER_MODEL,
    CONF_SERIAL,
    DEFAULT_ANALYSIS_INTERVAL,
    DEFAULT_ANALYSIS_MODEL,
    DEFAULT_AUTO_PAUSE,
    DEFAULT_CAMERA_PORT,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_CONSECUTIVE_DETECTIONS,
    DOMAIN,
    ANOMALY_TRANSLATIONS,
)
from .bambu.models import AIAnalysisResult, PrinterStatus
from .camera.snapshot import async_capture_snapshot, check_image_quality
from .ai_provider.client import AIClient

# Lazy import BambuLanClient to avoid paho-mqtt dependency at module load
# TYPE_CHECKING import for type hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .bambu.client import BambuLanClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class BambuMonitorData:
    """Coordinator data class."""
    printer_status: str = "idle"
    print_progress: float = 0.0
    bed_temperature: float = 0.0
    bed_target_temperature: float = 0.0
    nozzle_temperature: float = 0.0
    nozzle_target_temperature: float = 0.0
    remaining_time_min: int = 0
    layer_num: int = 0
    total_layer_count: int = 0
    fan_speed: int = 0
    printer_online: bool = False
    anomaly_detected: bool = False
    anomaly_type: str | None = None
    anomaly_confidence: float = 0.0
    last_analysis: AIAnalysisResult | None = None
    last_analysis_time: datetime | None = None
    last_error: str | None = None
    consecutive_anomaly_count: int = 0


class BambuAICoordinator(DataUpdateCoordinator[BambuMonitorData]):
    """Coordinate Bambu printer monitoring with AI analysis."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        # _entry must be set before super().__init__() because _get_update_interval() uses it
        self._entry = entry
        self._bambu_client: BambuLanClient | None = None
        self._ai_client: AIClient | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._get_update_interval(),
        )

        self._data = BambuMonitorData()

        # Internal state
        self._consecutive_anomaly_count = 0
        self._auto_pause_enabled = entry.options.get(
            CONF_AUTO_PAUSE, DEFAULT_AUTO_PAUSE
        )
        self._confidence_threshold = entry.options.get(
            CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD
        )
        self._consecutive_detections = entry.options.get(
            CONF_CONSECUTIVE_DETECTIONS, DEFAULT_CONSECUTIVE_DETECTIONS
        )
        self._analysis_requested = False

    @property
    def bambu_client(self) -> BambuLanClient | None:
        """Get the Bambu client instance."""
        return self._bambu_client

    def _get_update_interval(self) -> timedelta:
        """Get current update interval."""
        if self._entry:
            return timedelta(seconds=self._entry.options.get(
                CONF_ANALYSIS_INTERVAL, DEFAULT_ANALYSIS_INTERVAL
            ))
        return timedelta(seconds=DEFAULT_ANALYSIS_INTERVAL)

    async def _async_setup(self) -> None:
        """Set up the coordinator connections."""
        data = self._entry.data
        host = data[CONF_HOST]
        access_code = data[CONF_ACCESS_CODE]
        serial = data.get(CONF_SERIAL, "")
        api_key = data[CONF_AI_API_KEY]
        model = data.get(CONF_ANALYSIS_MODEL, DEFAULT_ANALYSIS_MODEL)

        _LOGGER.info("Setting up coordinator for %s (model: %s)", host, data.get(CONF_PRINTER_MODEL))

        # Check for debug/mock mode
        from .bambu.mock_client import MockBambuClient, is_mock_mode

        if is_mock_mode(host, access_code):
            _LOGGER.info("DEBUG MODE: Using simulated printer")
            self._bambu_client = MockBambuClient(host, access_code, serial)
        else:
            try:
                from .bambu.client import BambuLanClient
            except ImportError as err:
                _LOGGER.error("paho-mqtt not installed. Run: pip install paho-mqtt")
                raise RuntimeError(f"Missing dependency: paho-mqtt") from err
            self._bambu_client = BambuLanClient(host, access_code, serial)

        self._bambu_client.register_status_callback(self._on_printer_status_update)

        # Initialize AI client for image analysis
        self._ai_client = AIClient(api_key, model, self.hass)

        # Connect to printer
        _LOGGER.info("Connecting to printer at %s...", host)
        connected = await self._bambu_client.async_connect()
        _LOGGER.info("Printer connection %s", "succeeded" if connected else "failed")
        if connected:
            self._data.printer_online = True
            # Update serial if not set
            if not serial and self._bambu_client.serial:
                self._data.printer_status = self._map_printer_status(
                    self._bambu_client.status.gcode_state
                )

    async def _async_update_data(self) -> BambuMonitorData:
        """Fetch data from the printer and perform AI analysis."""
        # Ensure connected
        if not self._bambu_client or not self._bambu_client.is_connected:
            if self._bambu_client:
                _LOGGER.debug("Reconnecting to printer...")
                await self._bambu_client.async_connect()
            self._data.printer_online = self._bambu_client.is_connected if self._bambu_client else False
            self._data.last_error = "Printer not connected"
            return self._data

        self._data.printer_online = True

        # Get current status from MQTT
        status = self._bambu_client.status
        self._data.printer_status = self._map_printer_status(status.gcode_state)
        self._data.print_progress = status.print_progress
        self._data.bed_temperature = status.bed_temperature
        self._data.bed_target_temperature = status.bed_target_temperature
        self._data.nozzle_temperature = status.nozzle_temperature
        self._data.nozzle_target_temperature = status.nozzle_target_temperature
        self._data.remaining_time_min = status.remaining_time_sec // 60
        self._data.layer_num = status.layer_num
        self._data.total_layer_count = status.total_layer_count
        self._data.fan_speed = status.fan_speed

        _LOGGER.debug(
            "Printer status: %s, progress: %.1f%%, layers: %d/%d",
            self._data.printer_status,
            self._data.print_progress,
            self._data.layer_num,
            self._data.total_layer_count,
        )

        # Only analyze when actively printing
        if self._data.printer_status == "running" or self._analysis_requested:
            self._analysis_requested = False
            await self._perform_analysis()

        return self._data

    async def _perform_analysis(self) -> None:
        """Capture snapshot and send to AI for analysis."""
        if not self._bambu_client or not self._ai_client:
            return

        try:
            # Get config data (used for both real and mock mode)
            data = self._entry.data

            # Check for mock mode
            from .bambu.mock_client import MockBambuClient

            if isinstance(self._bambu_client, MockBambuClient):
                snapshot = self._bambu_client.snapshot_provider.get_snapshot()
                _LOGGER.debug("DEBUG MODE: Using mock snapshot for analysis")
            else:
                # Capture snapshot from real camera
                snapshot = await async_capture_snapshot(
                    data[CONF_HOST],
                    data[CONF_ACCESS_CODE],
                    data.get(CONF_CAMERA_PORT, DEFAULT_CAMERA_PORT),
                )

            if not snapshot:
                self._data.last_error = "Failed to capture camera snapshot"
                return

            # Check image quality before AI analysis
            quality_ok, quality_score = check_image_quality(snapshot)
            if not quality_ok:
                _LOGGER.warning(
                    "Image too blurry (quality=%.1f), skipping AI analysis",
                    quality_score,
                )
                self._data.last_error = (
                    f"画面不清晰，跳过AI检测 (清晰度: {quality_score:.0f})"
                )
                return

            # Build context for analysis
            context = {
                "model": data.get(CONF_PRINTER_MODEL, "Unknown"),
                "progress": self._data.print_progress,
                "bed_temp": self._data.bed_temperature,
                "bed_target": self._data.bed_target_temperature,
                "nozzle_temp": self._data.nozzle_temperature,
                "nozzle_target": self._data.nozzle_target_temperature,
                "current_layer": self._data.layer_num,
                "total_layers": self._data.total_layer_count,
            }

            # Call AI API for image analysis
            raw_response = await self._ai_client.async_analyze_image(
                snapshot, context
            )

            # Parse result
            result = AIAnalysisResult.from_api_response(raw_response)
            self._data.last_analysis = result
            self._data.last_analysis_time = result.analysis_time
            self._data.anomaly_confidence = result.confidence
            self._data.anomaly_type = result.anomaly_type
            self._data.last_error = None

            # Check for anomaly
            if result.anomaly_detected and result.confidence >= self._confidence_threshold:
                self._consecutive_anomaly_count += 1
                self._data.consecutive_anomaly_count = self._consecutive_anomaly_count

                _LOGGER.warning(
                    "Anomaly detected (%s): %s (confidence: %.2f, consecutive: %d/%d)",
                    result.anomaly_type,
                    result.description,
                    result.confidence,
                    self._consecutive_anomaly_count,
                    self._consecutive_detections,
                )

                # Auto-pause after consecutive detections
                if self._consecutive_anomaly_count >= self._consecutive_detections:
                    self._data.anomaly_detected = True

                    if self._auto_pause_enabled:
                        await self._async_pause_print()
                        self._consecutive_anomaly_count = 0  # Reset after pause

                    # Send notification
                    await self._async_send_notification(result)
            else:
                # Reset consecutive count if no anomaly or below threshold
                if self._consecutive_anomaly_count > 0:
                    _LOGGER.debug(
                        "Anomaly not confirmed, resetting consecutive count"
                    )
                    self._consecutive_anomaly_count = 0
                    self._data.consecutive_anomaly_count = 0
                    self._data.anomaly_detected = False

        except Exception as err:
            self._data.last_error = f"Analysis error: {err}"
            _LOGGER.error("Analysis error: %s", err)

    async def _async_pause_print(self) -> bool:
        """Pause the current print."""
        if not self._bambu_client:
            return False

        _LOGGER.warning("Auto-pausing print due to detected anomaly")
        result = await self._bambu_client.async_pause_print()
        if result:
            self._data.printer_status = "paused"
        else:
            self._data.last_error = "Failed to pause print via MQTT"
        return result

    async def async_pause_print(self) -> bool:
        """Manually pause the print (from button/service)."""
        if not self._bambu_client:
            return False
        result = await self._bambu_client.async_pause_print()
        if result:
            self._data.printer_status = "paused"
        return result

    async def async_resume_print(self) -> bool:
        """Resume the print."""
        if not self._bambu_client:
            return False
        result = await self._bambu_client.async_resume_print()
        if result:
            self._data.printer_status = "running"
            self._consecutive_anomaly_count = 0
            self._data.anomaly_detected = False
        return result

    async def async_stop_print(self) -> bool:
        """Stop the print."""
        if not self._bambu_client:
            return False
        result = await self._bambu_client.async_stop_print()
        if result:
            self._data.printer_status = "idle"
        return result

    async def async_analyze_now(self) -> None:
        """Trigger an immediate analysis."""
        self._analysis_requested = True
        await self.async_request_refresh()

    async def async_set_analysis_interval(self, interval: int) -> None:
        """Change the analysis interval."""
        if self._entry:
            options = dict(self._entry.options)
            options[CONF_ANALYSIS_INTERVAL] = interval
            self.hass.config_entries.async_update_entry(self._entry, options=options)
            self.update_interval = timedelta(seconds=interval)

    def _on_printer_status_update(self, status: PrinterStatus) -> None:
        """Handle printer status update from MQTT callback."""
        self._data.printer_status = self._map_printer_status(status.gcode_state)
        self._data.print_progress = status.print_progress
        self._data.bed_temperature = status.bed_temperature
        self._data.nozzle_temperature = status.nozzle_temperature
        self._data.remaining_time_min = status.remaining_time_sec // 60
        self._data.layer_num = status.layer_num
        self._data.total_layer_count = status.total_layer_count

    async def _async_send_notification(self, result: AIAnalysisResult) -> None:
        """Send a persistent notification with analysis result."""
        anomaly_name = ANOMALY_TRANSLATIONS.get(result.anomaly_type, result.anomaly_type)
        message = (
            f"打印异常检测: {anomaly_name}\n"
            f"置信度: {result.confidence:.0%}\n"
            f"描述: {result.description}\n"
            f"打印机: {self._entry.data.get(CONF_HOST)}"
        )

        if self._auto_pause_enabled:
            message += "\n\n打印已自动暂停。"

        async_create(
            self.hass,
            message=message,
            title="Bambu AI 打印监测",
            notification_id=f"bambu_anomaly_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )

    async def async_cleanup(self) -> None:
        """Clean up coordinator resources."""
        if self._bambu_client:
            await self._bambu_client.async_disconnect()
            self._bambu_client = None

    @staticmethod
    def _map_printer_status(gcode_state: str) -> str:
        """Map gcode_state to human-readable status."""
        mapping = {
            "IDLE": "idle",
            "PREPARE": "preparing",
            "RUNNING": "running",
            "PAUSE": "paused",
            "FINISH": "finished",
            "FAILED": "failed",
        }
        return mapping.get(gcode_state, "unknown")
