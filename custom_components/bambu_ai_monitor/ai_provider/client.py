"""Local YOLOv8 detection via ONNX Runtime for 3D print anomaly analysis.

Uses subprocess to call a Python script running on the HOST machine
(via SSH or direct execution), since the HA container uses musl libc
which is incompatible with onnxruntime's glibc binaries.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiohttp

from ..const import DEFAULT_INFERENCE_HOST, DEFAULT_INFERENCE_PORT

_LOGGER = logging.getLogger(__name__)


class YOLODetector:
    """HTTP client for host-side YOLO inference server."""

    def __init__(
        self,
        host: str = DEFAULT_INFERENCE_HOST,
        port: int = DEFAULT_INFERENCE_PORT,
    ) -> None:
        """Initialize the detector.

        Args:
            host: Inference server hostname (default: localhost)
            port: Inference server port (default: 19530)
        """
        self._host = host
        self._port = port
        self._base_url = f"http://{host}:{port}"

    @property
    def base_url(self) -> str:
        """Get the base URL of the inference server."""
        return self._base_url

    async def async_validate_connection(self) -> tuple[bool, str | None]:
        """Check if the inference server is reachable."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "ok":
                            return True, None
                        return False, f"推理服务器状态异常: {data.get('status')}"
                    return False, f"推理服务器返回 HTTP {response.status}"
        except aiohttp.ClientConnectorError:
            return (
                False,
                f"无法连接到推理服务器 ({self._base_url})\n"
                "请确保宿主机上已启动推理服务器:\n"
                "  python3 inference_server/server.py",
            )
        except Exception as err:
            return False, f"连接推理服务器出错: {err}"

    async def async_analyze_image(
        self,
        image_bytes: bytes,
        context: dict[str, Any],
    ) -> str:
        """Send image to host inference server for YOLO detection."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/analyze",
                    data=image_bytes,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return json.dumps(result)
                    else:
                        text = await response.text()
                        _LOGGER.error(
                            "Inference server error: HTTP %s - %s",
                            response.status,
                            text[:200],
                        )
                        return json.dumps({
                            "anomaly_detected": False,
                            "anomaly_type": "none",
                            "confidence": 0.0,
                            "description": f"推理服务器错误 (HTTP {response.status})",
                        })

        except aiohttp.ClientConnectorError:
            _LOGGER.error("Cannot connect to inference server at %s", self._base_url)
            return json.dumps({
                "anomaly_detected": False,
                "anomaly_type": "none",
                "confidence": 0.0,
                "description": "推理服务器未启动，请在宿主机运行: python3 inference_server/server.py",
            })
        except Exception as err:
            _LOGGER.error("Inference request error: %s", err)
            return json.dumps({
                "anomaly_detected": False,
                "anomaly_type": "none",
                "confidence": 0.0,
                "description": f"推理请求错误: {err}",
            })


    async def async_visualize_image(
        self,
        image_bytes: bytes,
    ) -> bytes | None:
        """Send image to host inference server and return annotated JPEG."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/visualize",
                    data=image_bytes,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        _LOGGER.warning(
                            "Visualize server error: HTTP %s", response.status
                        )
                        return None
        except aiohttp.ClientConnectorError:
            _LOGGER.error(
                "Cannot connect to visualize server at %s", self._base_url
            )
            return None
        except Exception as err:
            _LOGGER.error("Visualize request error: %s", err)
            return None


# Backward-compatible alias
AIClient = YOLODetector
