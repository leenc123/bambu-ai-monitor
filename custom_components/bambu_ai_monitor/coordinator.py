"""DataUpdateCoordinator for Bambu AI Print Monitor."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.persistent_notification import async_create

from .const import (
    CONF_ANALYSIS_INTERVAL,
    CONF_AUTO_PAUSE,
    CONF_CONFIDENCE_THRESHOLD,
    CONF_CONSECUTIVE_DETECTIONS,
    CONF_INFERENCE_HOST,
    CONF_INFERENCE_PORT,
    CONF_HOST,
    CONF_ACCESS_CODE,
    CONF_CAMERA_PORT,
    CONF_PRINTER_MODEL,
    CONF_SERIAL,
    DEFAULT_ANALYSIS_INTERVAL,
    DEFAULT_INFERENCE_HOST,
    DEFAULT_INFERENCE_PORT,
    DEFAULT_AUTO_PAUSE,
    DEFAULT_CAMERA_PORT,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_CONSECUTIVE_DETECTIONS,
    DOMAIN,
    ANOMALY_TRANSLATIONS,
)
from .bambu.models import AIAnalysisResult, PrinterStatus
from .camera.snapshot import async_capture_snapshot, check_image_quality
from .ai_provider.client import YOLODetector
from .service_manager import InferenceServerManager

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
        self._yolo_detector: YOLODetector | None = None

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
        self._last_annotated_image: bytes | None = None
        # Guards against overlapping analyses and enforces the configured cadence.
        self._analysis_lock = asyncio.Lock()
        self._last_analysis_monotonic = 0.0
        # Set once async_initialize() has run (works with and without the HA
        # 2024.8 `_async_setup` hook).
        self._initialized = False

        # Inference server lifecycle (options take precedence over entry data,
        # matching async_initialize(), so endpoint-change detection is stable).
        inference_host = entry.options.get(
            CONF_INFERENCE_HOST,
            entry.data.get(CONF_INFERENCE_HOST, DEFAULT_INFERENCE_HOST),
        )
        inference_port = entry.options.get(
            CONF_INFERENCE_PORT,
            entry.data.get(CONF_INFERENCE_PORT, DEFAULT_INFERENCE_PORT),
        )
        self._inference_endpoint = (inference_host, int(inference_port))
        self._inference_server = InferenceServerManager(
            inference_host=inference_host,
            inference_port=inference_port,
        )

    @property
    def bambu_client(self) -> BambuLanClient | None:
        """Get the Bambu client instance."""
        return self._bambu_client

    @property
    def inference_endpoint(self) -> tuple[str, int]:
        """Return the configured inference (host, port) endpoint."""
        return self._inference_endpoint

    @property
    def last_annotated_image(self) -> bytes | None:
        """Return the most recent annotated camera frame (if any)."""
        return self._last_annotated_image

    def async_apply_options(self, options: dict) -> None:
        """Apply runtime options in place without reloading the entry."""
        self._auto_pause_enabled = options.get(
            CONF_AUTO_PAUSE, DEFAULT_AUTO_PAUSE
        )
        self._confidence_threshold = options.get(
            CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD
        )
        self._consecutive_detections = options.get(
            CONF_CONSECUTIVE_DETECTIONS, DEFAULT_CONSECUTIVE_DETECTIONS
        )
        interval = options.get(CONF_ANALYSIS_INTERVAL, DEFAULT_ANALYSIS_INTERVAL)
        new_interval = timedelta(seconds=interval)
        if self.update_interval != new_interval:
            self.update_interval = new_interval
        self.async_update_listeners()

    def _analysis_due(self) -> bool:
        """Return True if enough time has elapsed since the last analysis."""
        interval = (
            self.update_interval.total_seconds()
            if self.update_interval
            else DEFAULT_ANALYSIS_INTERVAL
        )
        return (time.monotonic() - self._last_analysis_monotonic) >= interval

    def _clear_active_anomaly(self) -> None:
        """Clear the current anomaly state (used when a print ends/stops)."""
        self._consecutive_anomaly_count = 0
        self._data.consecutive_anomaly_count = 0
        self._data.anomaly_detected = False
        self._data.anomaly_type = "none"
        self._data.anomaly_confidence = 0.0

    def _get_update_interval(self) -> timedelta:
        """Get current update interval."""
        if self._entry:
            return timedelta(seconds=self._entry.options.get(
                CONF_ANALYSIS_INTERVAL, DEFAULT_ANALYSIS_INTERVAL
            ))
        return timedelta(seconds=DEFAULT_ANALYSIS_INTERVAL)

    async def async_initialize(self) -> None:
        """Set up the coordinator connections (idempotent)."""
        if self._initialized:
            return
        self._initialized = True
        data = self._entry.data
        host = data[CONF_HOST]
        access_code = data[CONF_ACCESS_CODE]
        serial = data.get(CONF_SERIAL, "")
        inference_host = self._entry.options.get(
            CONF_INFERENCE_HOST,
            data.get(CONF_INFERENCE_HOST, DEFAULT_INFERENCE_HOST),
        )
        inference_port = self._entry.options.get(
            CONF_INFERENCE_PORT,
            data.get(CONF_INFERENCE_PORT, DEFAULT_INFERENCE_PORT),
        )

        _LOGGER.info(
            "Setting up coordinator for %s (inference: %s:%s)",
            host,
            inference_host,
            inference_port,
        )

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
        try:
            self._bambu_client.register_connection_callback(
                self._on_connection_change
            )
        except AttributeError:
            # Older/mock clients may not expose the connection callback.
            pass

        # Initialize YOLO detector (connects to host inference server)
        self._yolo_detector = YOLODetector(inference_host, inference_port)

        # Connect to printer
        _LOGGER.info("Connecting to printer at %s...", host)
        connected = await self._bambu_client.async_connect()
        _LOGGER.info("Printer connection %s", "succeeded" if connected else "failed")

        # Check inference server reachability on host
        await self._inference_server.async_ensure_running()
        if connected:
            self._data.printer_online = True
            # Update serial if not set
            if not serial and self._bambu_client.serial:
                self._data.printer_status = self._map_printer_status(
                    self._bambu_client.status.gcode_state
                )

    async def _async_setup(self) -> None:
        """HA >= 2024.8 setup hook; delegates to async_initialize()."""
        await self.async_initialize()

    async def _async_update_data(self) -> BambuMonitorData:
        """Fetch data from the printer and perform AI analysis."""
        # Ensure connected — background _reconnect_loop handles retry with ping gate
        if not self._bambu_client or not self._bambu_client.is_connected:
            self._data.printer_online = False
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
        self._data.remaining_time_min = status.remaining_time_min
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

        # Periodically refresh inference server health status
        await self._inference_server.async_check_health()

        # Only analyze while a print is actually running (manual triggers are
        # allowed via _analysis_requested). Using progress/layer as a fallback
        # caused endless analysis of the empty bed after FINISH.
        is_printing = (
            self._data.printer_status == "running" or self._analysis_requested
        )

        if is_printing:
            if self._analysis_requested or self._analysis_due():
                self._analysis_requested = False
                await self._perform_analysis()
        elif self._data.printer_status in ("finished", "idle", "failed"):
            self._clear_active_anomaly()

        return self._data

    async def _perform_analysis(self) -> None:
        """Capture snapshot and run local YOLO detection."""
        if not self._bambu_client or not self._yolo_detector:
            return

        if self._analysis_lock.locked():
            _LOGGER.debug("Analysis already in progress, skipping this cycle")
            return

        async with self._analysis_lock:
            self._last_analysis_monotonic = time.monotonic()
            try:
                data = self._entry.data

                # Check for mock mode
                from .bambu.mock_client import MockBambuClient

                if isinstance(self._bambu_client, MockBambuClient):
                    snapshot = self._bambu_client.snapshot_provider.get_snapshot()
                    _LOGGER.debug("DEBUG MODE: Using mock snapshot for analysis")
                else:
                    # Try MQTT camera frame first (A1 Mini pushes JPEG via MQTT)
                    snapshot = None
                    if self._bambu_client.camera_frame:
                        snapshot = self._bambu_client.camera_frame
                        _LOGGER.debug(
                            "Got snapshot from MQTT camera: %d bytes", len(snapshot)
                        )

                    if not snapshot:
                        # Fallback 1: direct TLS/HTTP to printer port 6000
                        snapshot = await async_capture_snapshot(
                            data[CONF_HOST],
                            data[CONF_ACCESS_CODE],
                            data.get(CONF_CAMERA_PORT, DEFAULT_CAMERA_PORT),
                        )

                    if not snapshot:
                        # Fallback 2: use existing HA camera entity
                        snapshot = await self._capture_from_ha_camera()

                if not snapshot:
                    self._data.last_error = "Failed to capture camera snapshot"
                    return

                # Check image quality before detection. Run in an executor —
                # the variance calculation touches every pixel and must not
                # block the event loop.
                quality_ok, quality_score = await self.hass.async_add_executor_job(
                    check_image_quality, snapshot
                )
                if not quality_ok:
                    _LOGGER.warning(
                        "Image too blurry (quality=%.1f), skipping detection",
                        quality_score,
                    )
                    self._data.last_error = (
                        f"画面过于模糊，跳过检测 (清晰度: {quality_score:.0f})"
                    )
                    return

                # Run detection first so the anomaly decision is not delayed
                # by the (second) visualization request.
                raw_response = await self._yolo_detector.async_analyze_image(
                    snapshot, {}
                )
                result = AIAnalysisResult.from_api_response(raw_response)

                # Then fetch the annotated frame. Keep the previous frame on
                # failure instead of blanking the camera.
                try:
                    annotated = await self._yolo_detector.async_visualize_image(
                        snapshot
                    )
                    if annotated:
                        self._last_annotated_image = annotated
                        _LOGGER.debug(
                            "Annotated image updated: %d bytes", len(annotated)
                        )
                except Exception as vis_err:
                    _LOGGER.warning("Failed to get annotated image: %s", vis_err)

                self._data.last_analysis = result
                self._data.last_analysis_time = result.analysis_time
                self._data.last_error = None

                if (
                    result.anomaly_detected
                    and result.confidence >= self._confidence_threshold
                ):
                    self._consecutive_anomaly_count += 1
                    self._data.consecutive_anomaly_count = (
                        self._consecutive_anomaly_count
                    )
                    self._data.anomaly_type = result.anomaly_type
                    self._data.anomaly_confidence = result.confidence

                    _LOGGER.warning(
                        "Anomaly detected (%s): %s (confidence: %.2f, consecutive: %d/%d)",
                        result.anomaly_type,
                        result.description,
                        result.confidence,
                        self._consecutive_anomaly_count,
                        self._consecutive_detections,
                    )

                    if self._consecutive_anomaly_count >= self._consecutive_detections:
                        # Keep the anomaly flag latched so the binary sensor
                        # stays on until the print is resumed/cleared.
                        self._data.anomaly_detected = True

                        if self._auto_pause_enabled and self._data.printer_status == "running":
                            await self._async_pause_print()

                        await self._async_send_notification(result)
                else:
                    if self._consecutive_anomaly_count > 0:
                        _LOGGER.debug(
                            "Anomaly not confirmed, resetting consecutive count"
                        )
                    self._consecutive_anomaly_count = 0
                    self._data.consecutive_anomaly_count = 0
                    self._data.anomaly_detected = False
                    self._data.anomaly_type = "none"
                    self._data.anomaly_confidence = result.confidence

            except Exception as err:
                self._data.last_error = f"Analysis error: {err}"
                _LOGGER.error("Analysis error: %s", err)

    async def _capture_from_ha_camera(self) -> bytes | None:
        """Fallback: capture snapshot from HA camera entity (A1 Mini etc.)."""
        try:
            from homeassistant.components import camera as camera_comp

            # Find a camera entity from the Bambu Lab integration
            for state in self.hass.states.async_all():
                entity_id = state.entity_id
                if entity_id.startswith("camera.") and ("bambu" in entity_id.lower() or "a1" in entity_id.lower() or "printer" in entity_id.lower()):
                    image = await camera_comp.async_get_image(
                        self.hass, entity_id, timeout=10
                    )
                    if image and image.content:
                        _LOGGER.info("Got snapshot from HA camera: %s (%d bytes)", entity_id, len(image.content))
                        return image.content
            _LOGGER.warning("No Bambu Lab camera entity found in HA")
            return None
        except Exception as err:
            _LOGGER.warning("Failed to capture from HA camera: %s", err)
            return None

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
            self._clear_active_anomaly()
        return result

    async def async_stop_print(self) -> bool:
        """Stop the print."""
        if not self._bambu_client:
            return False
        result = await self._bambu_client.async_stop_print()
        if result:
            self._data.printer_status = "idle"
            self._clear_active_anomaly()
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
        """Handle printer status update from MQTT callback.

        This runs on the paho MQTT thread, NOT the HA event loop.
        All mutations of self._data and HA coordinator calls are
        posted to the event loop via call_soon_threadsafe to avoid
        thread-safety violations.
        """
        # Build a snapshot from the MQTT thread (reading PrinterStatus
        # is safe — it's owned by the MQTT thread at this point).
        new_status = self._map_printer_status(status.gcode_state)
        progress = status.print_progress
        layer_num = status.layer_num
        total_layer_count = status.total_layer_count

        _LOGGER.debug(
            "MQTT callback: gcode_state=%s -> printer_status=%s, progress=%.1f%%, layers=%d/%d",
            status.gcode_state,
            new_status,
            progress,
            layer_num,
            total_layer_count,
        )

        is_printing = new_status == "running"

        # Post data update and optional analysis trigger to the HA event loop.
        # This is the ONLY thread-safe way to interact with HA from MQTT callbacks.
        self.hass.loop.call_soon_threadsafe(
            self._async_apply_status_update,
            new_status,
            progress,
            status.bed_temperature,
            status.nozzle_temperature,
            status.remaining_time_min,
            layer_num,
            total_layer_count,
            is_printing,
        )

    def _async_apply_status_update(
        self,
        new_status: str,
        progress: float,
        bed_temp: float,
        nozzle_temp: float,
        remaining_min: int,
        layer_num: int,
        total_layer_count: int,
        is_printing: bool,
    ) -> None:
        """Apply MQTT status update on the HA event loop (thread-safe)."""
        self._data.printer_status = new_status
        self._data.print_progress = progress
        self._data.bed_temperature = bed_temp
        self._data.nozzle_temperature = nozzle_temp
        self._data.remaining_time_min = remaining_min
        self._data.layer_num = layer_num
        self._data.total_layer_count = total_layer_count

        # This is safe now — we're on the HA event loop
        self.async_set_updated_data(self._data)

        # Throttle: only kick a refresh when the configured interval has
        # elapsed. Without this, every MQTT push (several per second while
        # printing) bypassed the user's analysis interval entirely.
        if (
            is_printing
            and not self._analysis_requested
            and self._analysis_due()
        ):
            _LOGGER.debug(
                "Scheduling analysis (progress=%.1f%%, interval elapsed)",
                progress,
            )
            self._analysis_requested = True
            self.hass.async_create_task(self.async_request_refresh())

    def _on_connection_change(self, connected: bool) -> None:
        """Handle MQTT connect/disconnect (may run on the paho thread)."""
        self.hass.loop.call_soon_threadsafe(
            self._async_apply_connection_change, connected
        )

    def _async_apply_connection_change(self, connected: bool) -> None:
        """Apply connection state on the HA event loop immediately."""
        self._data.printer_online = connected
        if not connected:
            self._data.last_error = "Printer disconnected"
            self._clear_active_anomaly()
        else:
            self._data.last_error = None
        self.async_set_updated_data(self._data)

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
            # Fixed id: repeated detections update the same notification
            # instead of piling up a new one each time.
            notification_id=f"bambu_anomaly_{self._entry.entry_id}",
        )

    @property
    def inference_server(self) -> InferenceServerManager:
        """Get the inference server manager."""
        return self._inference_server

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
