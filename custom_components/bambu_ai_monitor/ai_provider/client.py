"""AI client for image analysis using 通义千问 (DashScope)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

from ..const import DEFAULT_ANALYSIS_MODEL

_LOGGER = logging.getLogger(__name__)

# DashScope (通义千问) OpenAI-compatible endpoint
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_CHAT_ENDPOINT = "/chat/completions"

# Prompt for 3D print quality analysis
ANALYSIS_PROMPT = """Analyze this 3D printer camera snapshot for print quality issues.

Check for these common failures:
- Spaghetti: tangled, stringy filament mess on the build plate
- Warping: corners or edges lifting from the build plate
- Layer shift: misaligned layers, visible steps on the print
- Under extrusion: gaps, thin walls, incomplete layers, missing filament
- Over extrusion: blobs, elephant foot, excess filament buildup
- Detachment: print completely detached from the build plate
- Other anomalies: anything else abnormal about the print

Respond ONLY with raw JSON. Do NOT use markdown code blocks, do NOT wrap in backticks. Use this exact format:
{"anomaly_detected": true/false, "anomaly_type": "spaghetti"|"warping"|"layer_shift"|"under_extrusion"|"over_extrusion"|"detachment"|"none"|"other", "confidence": 0.0-1.0, "description": "Brief explanation in Chinese"}"""


class AIClient:
    """Client for 通义千问 (DashScope) API with vision support."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_ANALYSIS_MODEL,
        hass: HomeAssistant | None = None,
        base_url: str = DASHSCOPE_BASE_URL,
    ) -> None:
        """Initialize the AI client.

        Args:
            api_key: DashScope API key
            model: Model name to use for analysis
            hass: HomeAssistant instance (for session reuse)
            base_url: API base URL
        """
        self._api_key = api_key
        self._model = model
        self._hass = hass
        self._base_url = base_url

    async def async_validate_api_key(self) -> tuple[bool, str | None]:
        """Validate the API key with a cheap text-only test call.

        Returns:
            Tuple of (is_valid, error_message_or_none)
        """
        try:
            session = self._get_session()

            async with session.post(
                f"{self._base_url}{DASHSCOPE_CHAT_ENDPOINT}",
                headers=self._get_headers(),
                json={
                    "model": "qwen-turbo",
                    "messages": [
                        {"role": "user", "content": "Say 'ok' in one word."},
                    ],
                    "max_tokens": 10,
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 200:
                    return True, None
                elif response.status == 401:
                    _LOGGER.error("API: Invalid API key (401 Unauthorized)")
                    return False, "API Key 无效，请检查通义千问 API Key 是否正确"
                elif response.status == 403:
                    body = await response.text()
                    _LOGGER.error("API: Forbidden (403), body=%s", body)
                    return False, "API 访问被拒绝 (403)，请检查账户状态或余额"
                elif response.status == 429:
                    return False, "API 调用频率超限 (429)，请稍后重试"
                elif response.status == 404:
                    body = await response.text()
                    _LOGGER.error(
                        "API: Model not found (404), body=%s", body,
                    )
                    return False, f"模型不存在，API 响应: {body}"
                else:
                    body = await response.text()
                    _LOGGER.error(
                        "API validation failed: status=%s, body=%s",
                        response.status,
                        body,
                    )
                    return False, f"API 验证失败 (HTTP {response.status}): {body}"

        except aiohttp.ClientConnectorError as err:
            _LOGGER.error("API connection error: %s", err)
            return False, f"网络连接错误: {err}"
        except asyncio.TimeoutError:
            _LOGGER.error("API timeout")
            return False, "API 请求超时，请检查网络连接"
        except aiohttp.ClientError as err:
            _LOGGER.error("API network error: %s", err)
            return False, f"网络错误: {err}"
        except Exception as err:
            _LOGGER.error("API unexpected error: %s", err)
            return False, f"未知错误: {err}"

    async def async_analyze_image(
        self,
        image_bytes: bytes,
        context: dict[str, Any],
    ) -> str:
        """Send image to 通义千问 VL API for print quality analysis.

        Uses the OpenAI-compatible chat completions API with base64-encoded
        image content inline in the messages.

        Args:
            image_bytes: JPEG image bytes
            context: Printer context dict (unused for API, kept for compatibility)

        Returns:
            Raw content string from the AI response
        """
        try:
            session = self._get_session()

            # Encode image as base64 data URI
            b64_image = base64.b64encode(image_bytes).decode("utf-8")

            # Build multimodal message (OpenAI-compatible format)
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ANALYSIS_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_image}",
                            },
                        },
                    ],
                },
            ]

            async with session.post(
                f"{self._base_url}{DASHSCOPE_CHAT_ENDPOINT}",
                headers=self._get_headers(),
                json={
                    "model": self._model,
                    "messages": messages,
                    "max_tokens": 512,
                },
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    # Standard chat completions response
                    content = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    if not content:
                        content = json.dumps(data)
                    _LOGGER.debug("AI API response: %s", content)
                    return content
                elif response.status == 401:
                    _LOGGER.error("API: Invalid API key (401)")
                    return json.dumps({
                        "anomaly_detected": False,
                        "anomaly_type": "none",
                        "confidence": 0.0,
                        "description": "API Key 无效",
                    })
                elif response.status == 429:
                    _LOGGER.warning("API rate limit exceeded (429)")
                    return json.dumps({
                        "anomaly_detected": False,
                        "anomaly_type": "none",
                        "confidence": 0.0,
                        "description": "API 调用频率超限",
                    })
                else:
                    body = await response.text()
                    _LOGGER.error(
                        "API error: status=%s, body=%s",
                        response.status,
                        body,
                    )
                    return json.dumps({
                        "anomaly_detected": False,
                        "anomaly_type": "other",
                        "confidence": 0.0,
                        "description": f"API 错误: HTTP {response.status} - {body[:200]}",
                    })

        except aiohttp.ClientError as err:
            _LOGGER.error("API network error: %s", err)
            return json.dumps({
                "anomaly_detected": False,
                "anomaly_type": "none",
                "confidence": 0.0,
                "description": f"网络错误: {err}",
            })
        except Exception as err:
            _LOGGER.error("API unexpected error: %s", err)
            return json.dumps({
                "anomaly_detected": False,
                "anomaly_type": "none",
                "confidence": 0.0,
                "description": f"未知错误: {err}",
            })

    def _get_headers(self) -> dict[str, str]:
        """Get API request headers."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _get_session(self) -> aiohttp.ClientSession:
        """Get an aiohttp session, preferring Home Assistant's shared session."""
        if self._hass:
            return async_get_clientsession(self._hass)
        return aiohttp.ClientSession()


# Backward-compatible alias for existing imports
DeepSeekClient = AIClient
