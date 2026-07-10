"""Bambu Lab printer LAN client using MQTT."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .models import PrinterStatus, parse_printer_status

_LOGGER = logging.getLogger(__name__)

DEFAULT_MQTT_PORT = 8883
DEFAULT_TIMEOUT = 30


class BambuLanClient:
    """Async MQTT client for Bambu Lab printer LAN communication."""

    def __init__(
        self,
        host: str,
        access_code: str,
        serial: str = "",
        port: int = DEFAULT_MQTT_PORT,
    ) -> None:
        """Initialize the client."""
        self._host = host
        self._access_code = access_code
        self._serial = serial
        self._port = port
        self._client: mqtt.Client | None = None
        self._connected = False
        self._status: PrinterStatus = PrinterStatus()
        self._status_callbacks: list[Callable[[PrinterStatus], None]] = []
        self._connection_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task | None = None
        self._should_reconnect = True
        self._latest_camera_frame: bytes | None = None
        self._camera_callbacks: list[Callable[[bytes], None]] = []
        # Event loop reference for cross-thread callbacks (set in async_connect)
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def status(self) -> PrinterStatus:
        """Get current printer status."""
        return self._status

    @property
    def camera_frame(self) -> bytes | None:
        """Get the latest camera frame from MQTT (A1 Mini etc.)."""
        return self._latest_camera_frame

    def register_camera_callback(
        self, callback: Callable[[bytes], None]
    ) -> None:
        """Register a callback for incoming camera frames."""
        self._camera_callbacks.append(callback)

    def unregister_camera_callback(
        self, callback: Callable[[bytes], None]
    ) -> None:
        """Unregister a camera callback."""
        if callback in self._camera_callbacks:
            self._camera_callbacks.remove(callback)

    @property
    def is_connected(self) -> bool:
        """Return whether connected to printer."""
        return self._connected

    @property
    def serial(self) -> str:
        """Get printer serial."""
        return self._serial

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
        """Connect to printer via MQTT."""
        async with self._connection_lock:
            if self._connected:
                return True

            try:
                loop = asyncio.get_event_loop()

                self._loop = asyncio.get_event_loop()

                # 1. Create client — same config as bambulabs_api (works in Docker)
                self._client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"bambu_ai_{id(self)}",
                    protocol=mqtt.MQTTv311,
                )

                # 2. Enable paho's internal logger for debug
                self._client.enable_logger()

                # 3. TLS — skip cert verification (self-signed printer cert)
                self._client.tls_set(
                    cert_reqs=ssl.CERT_NONE,
                )
                self._client.tls_insecure_set(True)

                # 4. Auth
                self._client.username_pw_set("bblp", password=self._access_code)

                # 5. Callbacks (VERSION2 signatures)
                self._client.on_connect = self._on_connect
                self._client.on_disconnect = self._on_disconnect
                self._client.on_message = self._on_message

                # 6. Use connect_async (non-blocking) like bambulabs_api
                await loop.run_in_executor(
                    None,
                    lambda: self._client.connect_async(
                        self._host, self._port, 60
                    ),
                )

                # 7. Start network loop
                self._client.loop_start()
                self._should_reconnect = True

                # 8. Wait up to 30s for CONNACK
                for _ in range(DEFAULT_TIMEOUT * 10):
                    if self._connected:
                        break
                    await asyncio.sleep(0.1)
                else:
                    _LOGGER.warning(
                        "MQTT CONNACK timeout for %s:%s",
                        self._host, self._port,
                    )
                    self._client.loop_stop()
                    self._client.disconnect()
                    self._client = None
                    self._start_reconnect_safe()
                    return False

                # 9. Subscribe AFTER CONNACK confirmed
                if self._serial:
                    self._client.subscribe(
                        f"device/{self._serial}/report", qos=0
                    )
                else:
                    self._client.subscribe("device/#", qos=0)

                return self._connected

            except Exception as err:
                _LOGGER.error(
                    "Failed to connect to printer %s:%s - %s",
                    self._host, self._port, err,
                )
                self._connected = False
                if self._client:
                    try:
                        self._client.loop_stop()
                    except Exception:
                        pass
                    self._client = None
                # Start background retry
                self._should_reconnect = True
                self._start_reconnect_safe()
                return False

    async def async_disconnect(self) -> None:
        """Disconnect from printer."""
        """Disconnect from printer."""
        self._should_reconnect = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self._client:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._client.loop_stop)
                await loop.run_in_executor(None, self._client.disconnect)
            except Exception:
                pass
            self._client = None

        self._connected = False

    async def async_test_connection(self) -> bool:
        """Test if printer is reachable."""
        try:
            loop = asyncio.get_event_loop()

            test_client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"bambu_test_{id(self)}",
            )

            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            test_client.tls_set_context(ssl_ctx)
            test_client.username_pw_set("bblp", password=self._access_code)

            result_future = asyncio.Future()

            def on_connect(client, userdata, flags, rc, properties=None):
                if rc == 0:
                    result_future.set_result(True)
                else:
                    result_future.set_result(False)

            test_client.on_connect = on_connect

            await loop.run_in_executor(
                None,
                lambda: test_client.connect(self._host, self._port, 5),
            )

            test_client.loop_start()

            try:
                result = await asyncio.wait_for(result_future, timeout=DEFAULT_TIMEOUT)
                return result
            except asyncio.TimeoutError:
                return False
            finally:
                test_client.loop_stop()
                test_client.disconnect()

        except Exception as err:
            _LOGGER.warning("Printer connection test failed: %s", err)
            return False

    async def async_send_command(self, payload: str) -> bool:
        """Send a command to the printer via MQTT."""
        if not self._connected or not self._client:
            _LOGGER.error("Cannot send command: not connected")
            return False

        topic = f"device/{self._serial}/request"

        try:
            loop = asyncio.get_event_loop()
            # Publish + wait_for_publish both in executor to avoid blocking HA event loop
            ok = await loop.run_in_executor(
                None,
                lambda: self._do_publish(topic, payload),
            )
            if ok:
                _LOGGER.debug("Command sent to %s: %s", topic, payload[:100])
            return ok
        except Exception as err:
            _LOGGER.error("Failed to send command: %s", err)
            return False

    async def async_pause_print(self) -> bool:
        """Pause the current print."""
        from .commands import BambuCommands
        payload = BambuCommands.build_pause_command()
        return await self.async_send_command(payload)

    async def async_resume_print(self) -> bool:
        """Resume a paused print."""
        from .commands import BambuCommands
        payload = BambuCommands.build_resume_command()
        return await self.async_send_command(payload)

    async def async_stop_print(self) -> bool:
        """Stop the current print."""
        from .commands import BambuCommands
        payload = BambuCommands.build_stop_command()
        return await self.async_send_command(payload)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        """Handle MQTT connect callback (VERSION2 signature).

        Subscribe is done in async_connect() after CONNACK is confirmed,
        not here, to avoid race conditions with the printer's MQTT broker
        (A1 Mini disconnects immediately if SUBSCRIBE arrives too fast).
        """
        _LOGGER.info("MQTT on_connect called, rc=%s, host=%s", reason_code, self._host)
        if reason_code == 0:
            self._connected = True
            _LOGGER.info("Connected to printer %s", self._host)
        else:
            _LOGGER.error("Failed to connect with result code %s", reason_code)
            self._connected = False

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None) -> None:
        """Handle MQTT disconnect callback (VERSION2 signature)."""
        self._connected = False
        _LOGGER.info("Disconnected from printer %s (reason_code=%s)", self._host, reason_code)

        if self._should_reconnect and self._loop is not None:
            self._loop.call_soon_threadsafe(self._start_reconnect_safe)

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        # Log all topics for debugging
        _LOGGER.debug("MQTT message on topic: %s (%d bytes)", msg.topic, len(msg.payload))

        # Check for camera frames (binary JPEG data on MQTT camera topics)
        if "camera" in msg.topic.lower() or "ipcam" in msg.topic.lower():
            payload = msg.payload
            # Check if it looks like a JPEG (starts with FF D8)
            if len(payload) > 2 and payload[0] == 0xFF and payload[1] == 0xD8:
                self._latest_camera_frame = payload
                _LOGGER.info("Camera frame received via MQTT: %s (%d bytes)", msg.topic, len(payload))
                for callback in self._camera_callbacks:
                    try:
                        callback(payload)
                    except Exception:
                        _LOGGER.exception("Error in camera callback")
                return

        # Parse JSON status messages
        try:
            payload = json.loads(msg.payload)
            self._status = parse_printer_status(payload)

            # Extract serial if not set
            if not self._serial:
                self._serial = payload.get("print", {}).get("sequence_id", "")
                if not self._serial:
                    parts = msg.topic.split("/")
                    if len(parts) >= 2:
                        self._serial = parts[1]

            # Notify callbacks
            for callback in self._status_callbacks:
                try:
                    callback(self._status)
                except Exception:
                    _LOGGER.exception("Error in status callback")

        except json.JSONDecodeError:
            pass
        except Exception:
            _LOGGER.exception("Error parsing MQTT message")

    def _start_reconnect_safe(self) -> None:
        """Safely start reconnection from the event loop thread."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._reconnect_task = loop.create_task(self._reconnect_loop())
        except RuntimeError:
            pass

    async def _reconnect_loop(self):
        """Reconnection loop with TCP ping gate + stepped backoff.

        Wait sequence: 10s → 30s → 60s → 300s (cap at 5 min).
        Before each MQTT connect, check host reachability by probing the
        MQTT port with a short timeout. Skip connect if host is unreachable.
        """
        backoff = [10, 30, 60, 300]
        idx = 0
        while self._should_reconnect and not self._connected:
            delay = backoff[min(idx, len(backoff) - 1)]
            _LOGGER.info(
                "Reconnect check in %ss (attempt %d)...",
                delay, idx + 1,
            )
            await asyncio.sleep(delay)
            idx += 1

            # Ping gate: probe MQTT port before attempting full connect
            reachable = await self._async_check_reachable()
            if not reachable:
                _LOGGER.debug(
                    "Printer %s:%s not reachable, deferring connect",
                    self._host, self._port,
                )
                continue

            if await self.async_connect():
                break

    async def _async_check_reachable(self, timeout: int = 3) -> bool:
        """Check if the printer MQTT port is reachable via TCP.

        Opens a short TCP connection to the MQTT port and immediately
        closes it. This is cross-platform and doesn't depend on ICMP.
        Returns True if the port accepts the connection.
        """
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    def _do_publish(self, topic: str, payload: str) -> bool:
        """Synchronous publish + wait (runs in executor thread)."""
        if not self._client:
            return False
        try:
            info = self._client.publish(topic, payload, qos=1)
            info.wait_for_publish()
            return info.is_published()
        except Exception:
            return False

    def _start_reconnect(self) -> None:
        """Start reconnection attempt."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        try:
            loop = asyncio.get_event_loop()
            self._reconnect_task = loop.create_task(self._reconnect_loop())
        except RuntimeError:
            self._start_reconnect_safe()
