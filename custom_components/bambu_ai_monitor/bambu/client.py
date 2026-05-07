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
DEFAULT_TIMEOUT = 10


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

    @property
    def status(self) -> PrinterStatus:
        """Get current printer status."""
        return self._status

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

                self._client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"bambu_ai_{id(self)}",
                )

                # SSL configuration
                ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

                self._client.tls_set_context(ssl_ctx)
                self._client.username_pw_set("bblp", password=self._access_code)

                self._client.on_connect = self._on_connect
                self._client.on_disconnect = self._on_disconnect
                self._client.on_message = self._on_message

                await loop.run_in_executor(
                    None,
                    lambda: self._client.connect(
                        self._host, self._port, 60
                    ),
                )

                self._client.loop_start()
                self._should_reconnect = True

                # Wait for connection
                for _ in range(DEFAULT_TIMEOUT * 10):
                    if self._connected:
                        break
                    await asyncio.sleep(0.1)
                else:
                    _LOGGER.warning("Connection timeout to %s:%s", self._host, self._port)
                    await self.async_disconnect()
                    return False

                return self._connected

            except Exception as err:
                _LOGGER.error("Failed to connect to printer %s: %s", self._host, err)
                await self.async_disconnect()
                return False

    async def async_disconnect(self) -> None:
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
            info = await loop.run_in_executor(
                None,
                lambda: self._client.publish(topic, payload, qos=1),
            )
            info.wait_for_publish()
            _LOGGER.debug("Command sent to %s: %s", topic, payload[:100])
            return True
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

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        """Handle MQTT connect callback."""
        if rc == 0:
            self._connected = True
            _LOGGER.info("Connected to printer %s", self._host)

            # Subscribe to status topic
            if self._serial:
                topic = f"device/{self._serial}/report"
                client.subscribe(topic, qos=1)
            else:
                client.subscribe("device/#", qos=1)
        else:
            _LOGGER.error("Failed to connect with result code %s", rc)
            self._connected = False

    def _on_disconnect(self, client, userdata, flags, rc, properties=None) -> None:
        """Handle MQTT disconnect callback."""
        self._connected = False
        _LOGGER.info("Disconnected from printer %s", self._host)

        if self._should_reconnect and rc != 0:
            self._start_reconnect()

    def _on_message(self, client, userdata, msg) -> None:
        """Handle incoming MQTT messages."""
        try:
            payload = json.loads(msg.payload)
            self._status = parse_printer_status(payload)

            # Extract serial if not set
            if not self._serial:
                self._serial = payload.get("print", {}).get("sequence_id", "")
                if not self._serial:
                    # Try to extract from topic
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

    def _start_reconnect(self) -> None:
        """Start reconnection attempt."""
        if self._reconnect_task and not self._reconnect_task.done():
            return

        async def _reconnect_loop():
            delay = 1
            while self._should_reconnect and not self._connected:
                _LOGGER.info(
                    "Attempting to reconnect in %s seconds...", delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
                if await self.async_connect():
                    break

        loop = asyncio.get_event_loop()
        self._reconnect_task = loop.create_task(_reconnect_loop())
