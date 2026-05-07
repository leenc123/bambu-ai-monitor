"""Mock/simulated Bambu Lab printer for development and testing."""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import random
import os
import time
from pathlib import Path
from typing import Callable

from .models import PrinterStatus

_LOGGER = logging.getLogger(__name__)

# Path to test snapshot images (relative to integration dir or absolute)
_SNAPSHOTS_DIR = Path(__file__).parent.parent / "snapshots"

# Simulated print duration in seconds
MOCK_PRINT_DURATION = 600  # 10 minutes for faster testing


class MockSnapshotProvider:
    """Provides test snapshot images from a local directory."""

    def __init__(self) -> None:
        """Initialize the mock snapshot provider."""
        self._anomaly_triggered: bool = False
        self._normal_images: list[tuple[str, bytes]] = []
        self._anomaly_images: list[tuple[str, bytes]] = []
        self._current_anomaly_idx = 0
        self._current_normal_idx = 0
        self._load_images()

    def _load_images(self) -> None:
        """Load test images from the snapshots directory."""
        if not _SNAPSHOTS_DIR.exists():
            _LOGGER.warning("Snapshots dir not found: %s", _SNAPSHOTS_DIR)
            return

        # Load normal images
        normal_files = sorted(glob.glob(str(_SNAPSHOTS_DIR / "normal" / "*")))
        for fp in normal_files:
            try:
                with open(fp, "rb") as f:
                    self._normal_images.append((os.path.basename(fp), f.read()))
            except Exception as err:
                _LOGGER.warning("Failed to load %s: %s", fp, err)

        # Load anomaly images
        anomaly_files = sorted(glob.glob(str(_SNAPSHOTS_DIR / "anomaly" / "*")))
        for fp in anomaly_files:
            try:
                with open(fp, "rb") as f:
                    self._anomaly_images.append((os.path.basename(fp), f.read()))
            except Exception as err:
                _LOGGER.warning("Failed to load %s: %s", fp, err)

        _LOGGER.info(
            "MockSnapshotProvider loaded: %d normal, %d anomaly images from %s",
            len(self._normal_images),
            len(self._anomaly_images),
            _SNAPSHOTS_DIR,
        )

    def get_snapshot(self) -> bytes | None:
        """Return the next snapshot image based on current anomaly state.

        Cycles through loaded images. Falls back to generated images if none loaded.
        """
        if self._anomaly_triggered and self._anomaly_images:
            name, data = self._anomaly_images[self._current_anomaly_idx % len(self._anomaly_images)]
            self._current_anomaly_idx += 1
            _LOGGER.debug("DEBUG MODE: Serving anomaly snapshot: %s", name)
            return data

        if not self._anomaly_triggered and self._normal_images:
            name, data = self._normal_images[self._current_normal_idx % len(self._normal_images)]
            self._current_normal_idx += 1
            _LOGGER.debug("DEBUG MODE: Serving normal snapshot: %s", name)
            return data

        # Fallback: generate a simple image
        _LOGGER.warning("No images loaded, generating fallback snapshot")
        return self._generate_fallback()

    def _generate_fallback(self) -> bytes:
        """Generate a simple fallback JPEG image when no real images are available."""
        try:
            from PIL import Image
            import io

            width, height = 640, 480
            image = Image.new("RGB", (width, height), (30, 30, 30))

            plate_color = (80, 80, 80)
            plate_x, plate_y = 40, 40
            plate_w, plate_h = width - 80, height - 80
            for y in range(plate_y, plate_y + plate_h):
                for x in range(plate_x, plate_x + plate_w):
                    image.putpixel((x, y), plate_color)

            if self._anomaly_triggered:
                print_color = (200, 100, 50)
                for _ in range(500):
                    x = random.randint(plate_x, plate_x + plate_w - 1)
                    y = random.randint(plate_y, plate_y + plate_h - 1)
                    image.putpixel((x, y), print_color)
            else:
                print_color = (50, 180, 50)
                obj_x, obj_y = width // 2 - 60, height // 2 - 60
                for y in range(obj_y, obj_y + 120):
                    for x in range(obj_x, obj_x + 120):
                        image.putpixel((x, y), print_color)

            output = io.BytesIO()
            image.save(output, format="JPEG", quality=80)
            return output.getvalue()
        except Exception as err:
            _LOGGER.error("Failed to generate fallback image: %s", err)
            # Minimal valid JPEG
            return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"



class MockBambuClient:
    """Simulated Bambu Lab printer for development and testing.

    Mimics the BambuLanClient interface but generates fake printer status
    updates instead of connecting to a real printer via MQTT.

    Usage: Set CONF_HOST to "mock" or "127.0.0.1" with special access_code
    "DEBUG_MODE" to activate this simulated printer.
    """

    def __init__(
        self,
        host: str,
        access_code: str,
        serial: str = "",
        port: int = 8883,
    ) -> None:
        """Initialize the mock client."""
        self._host = host
        self._access_code = access_code
        self._serial = serial or "MOCK_SERIAL_001"
        self._port = port
        self._connected = False
        self._status = PrinterStatus()
        self._status_callbacks: list[Callable[[PrinterStatus], None]] = []
        self._simulation_task: asyncio.Task | None = None
        self._should_run = False

        # Simulation state
        self._sim_start_time = 0.0
        self._sim_print_duration = MOCK_PRINT_DURATION
        self._sim_anomaly_active = False
        self._sim_anomaly_count = 0

        self._snapshot_provider = MockSnapshotProvider()
        # Link provider to this client's anomaly state
        self._snapshot_provider._check_anomaly = lambda: self._sim_anomaly_active

        # Wrap get_snapshot to respect our anomaly state
        self._original_get_snapshot = self._snapshot_provider.get_snapshot
        self._snapshot_provider.get_snapshot = self._get_snapshot_with_anomaly

    def _get_snapshot_with_anomaly(self) -> bytes | None:
        """Get snapshot that respects the client's anomaly state."""
        self._snapshot_provider._anomaly_triggered = self._sim_anomaly_active
        return self._original_get_snapshot()

    @property
    def status(self) -> PrinterStatus:
        """Get current printer status."""
        return self._status

    @property
    def is_connected(self) -> bool:
        """Return whether connected."""
        return self._connected

    @property
    def serial(self) -> str:
        """Get printer serial."""
        return self._serial

    @property
    def snapshot_provider(self) -> MockSnapshotProvider:
        """Get the mock snapshot provider."""
        return self._snapshot_provider

    def register_status_callback(
        self, callback: Callable[[PrinterStatus], None]
    ) -> None:
        """Register a callback for status updates."""
        self._status_callbacks.append(callback)

    def unregister_status_callback(
        self, callback: Callable[[PrinterStatus], None]
    ) -> None:
        """Unregister a status callback."""
        if callback in self._status_callbacks:
            self._status_callbacks.remove(callback)

    async def async_connect(self) -> bool:
        """Simulate connecting to printer."""
        _LOGGER.info(
            "[DEBUG MODE] Simulating connection to Bambu printer at %s (print duration: %ds)",
            self._host,
            self._sim_print_duration,
        )
        self._connected = True
        self._should_run = True
        self._sim_start_time = time.time()
        self._sim_anomaly_count = 0

        # Start simulation loop
        loop = asyncio.get_event_loop()
        self._simulation_task = loop.create_task(self._simulate_print_loop())

        return True

    async def async_disconnect(self) -> None:
        """Disconnect from simulated printer."""
        self._should_run = False
        if self._simulation_task:
            self._simulation_task.cancel()
            self._simulation_task = None
        self._connected = False
        _LOGGER.info("[DEBUG MODE] Mock printer disconnected")

    async def async_test_connection(self) -> bool:
        """Test if mock printer is reachable."""
        return True

    async def async_send_command(self, payload: str) -> bool:
        """Handle simulated commands."""
        try:
            data = json.loads(payload)
            command = data.get("print", {}).get("command", "")
            _LOGGER.info("[DEBUG MODE] Received command: %s", command)

            if command == "pause":
                self._status.gcode_state = "PAUSE"
            elif command == "resume":
                self._status.gcode_state = "RUNNING"
            elif command == "stop":
                self._status.gcode_state = "IDLE"
                self._status.print_progress = 0.0

            # Notify callbacks
            for callback in self._status_callbacks:
                try:
                    callback(self._status)
                except Exception:
                    pass

            return True
        except Exception as err:
            _LOGGER.error("[DEBUG MODE] Command error: %s", err)
            return False

    async def async_pause_print(self) -> bool:
        """Pause the simulated print."""
        return await self.async_send_command(
            '{"print": {"command": "pause", "param": "", "sequence_id": "0"}}'
        )

    async def async_resume_print(self) -> bool:
        """Resume the simulated print."""
        return await self.async_send_command(
            '{"print": {"command": "resume", "param": "", "sequence_id": "0"}}'
        )

    async def async_stop_print(self) -> bool:
        """Stop the simulated print."""
        return await self.async_send_command(
            '{"print": {"command": "stop", "param": "", "sequence_id": "0"}}'
        )

    async def _simulate_print_loop(self) -> None:
        """Simulate a print progressing over time."""
        _LOGGER.info("[DEBUG MODE] Starting print simulation (%.1f min)", self._sim_print_duration / 60)

        # Start with "running" state
        self._status.gcode_state = "RUNNING"
        self._status.online = True
        self._status.bed_temperature = 60.0
        self._status.bed_target_temperature = 60.0
        self._status.nozzle_temperature = 240.0
        self._status.nozzle_target_temperature = 240.0
        self._status.total_layer_count = 200

        while self._should_run:
            if self._status.gcode_state == "RUNNING":
                elapsed = time.time() - self._sim_start_time
                progress = min(100.0, (elapsed / self._sim_print_duration) * 100)

                self._status.print_progress = progress
                self._status.mc_percent = int(progress)
                self._status.remaining_time_sec = int(
                    (100 - progress) / 100 * self._sim_print_duration
                )
                self._status.layer_num = int(progress / 100 * self._status.total_layer_count)

                # Temperature fluctuation
                self._status.bed_temperature = 60.0 + random.uniform(-1.0, 1.0)
                self._status.nozzle_temperature = 240.0 + random.uniform(-2.0, 2.0)
                self._status.fan_speed = random.randint(80, 100)

                # Simulate anomaly at certain points
                self._check_anomaly_trigger(progress)

            # Notify callbacks
            for callback in self._status_callbacks:
                try:
                    callback(self._status)
                except Exception:
                    pass

            await asyncio.sleep(5)  # Update every 5 seconds

    def _check_anomaly_trigger(self, progress: float) -> None:
        """Trigger simulated anomalies at specific progress points."""
        # Anomaly window: 25-35% (spaghetti) and 65-75% (warping)
        if 25 <= progress <= 35:
            if not self._sim_anomaly_active:
                self._sim_anomaly_active = True
                self._sim_anomaly_count += 1
                _LOGGER.info(
                    "[DEBUG MODE] Anomaly #%d triggered at %.1f%%: serving anomaly images",
                    self._sim_anomaly_count,
                    progress,
                )
        elif 65 <= progress <= 75:
            if not self._sim_anomaly_active:
                self._sim_anomaly_active = True
                self._sim_anomaly_count += 1
                _LOGGER.info(
                    "[DEBUG MODE] Anomaly #%d triggered at %.1f%%: serving anomaly images",
                    self._sim_anomaly_count,
                    progress,
                )
        else:
            if self._sim_anomaly_active:
                self._sim_anomaly_active = False
                _LOGGER.info("[DEBUG MODE] Anomaly cleared at %.1f%%", progress)


def is_mock_mode(host: str, access_code: str) -> bool:
    """Check if the configuration indicates mock/debug mode."""
    return host.lower() in ("mock", "debug", "127.0.0.1") and access_code == "DEBUG_MODE"
