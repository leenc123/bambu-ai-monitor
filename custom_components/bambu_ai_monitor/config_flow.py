"""Config flow for Bambu AI Print Monitor."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback

from .const import (
    CONF_ACCESS_CODE,
    CONF_INFERENCE_HOST,
    CONF_INFERENCE_PORT,
    CONF_ANALYSIS_INTERVAL,
    CONF_AUTO_PAUSE,
    CONF_CAMERA_PORT,
    CONF_CONFIDENCE_THRESHOLD,
    CONF_CONSECUTIVE_DETECTIONS,
    CONF_PRINTER_MODEL,
    CONF_SERIAL,
    CONF_YOLO_MODEL_PATH,
    DEFAULT_ANALYSIS_INTERVAL,
    DEFAULT_INFERENCE_HOST,
    DEFAULT_INFERENCE_PORT,
    DEFAULT_AUTO_PAUSE,
    DEFAULT_CAMERA_PORT,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_CONSECUTIVE_DETECTIONS,
    DEFAULT_MQTT_PORT,
    DEFAULT_YOLO_MODEL_PATH,
    DOMAIN,
    PrinterModel,
)

_LOGGER = logging.getLogger(__name__)

# 中文字段标签 — 用作 schema key，HA config flow 不翻译自定义组件时直接显示 key
_LABEL = {
    CONF_HOST: "打印机 IP 地址",
    CONF_ACCESS_CODE: "局域网访问码",
    CONF_SERIAL: "打印机序列号（可选）",
    CONF_PRINTER_MODEL: "打印机型号",
    CONF_CAMERA_PORT: "摄像头端口",
    CONF_YOLO_MODEL_PATH: "YOLO ONNX 模型路径",
    CONF_INFERENCE_HOST: "推理服务器地址",
    CONF_INFERENCE_PORT: "推理服务器端口",
    CONF_ANALYSIS_INTERVAL: "分析间隔",
    CONF_CONFIDENCE_THRESHOLD: "置信度阈值",
    CONF_AUTO_PAUSE: "异常时自动暂停",
    CONF_CONSECUTIVE_DETECTIONS: "触发暂停的连续检测次数",
}

# label → const key 反向映射（转换 user_input）
_label_to_key = {v: k for k, v in _LABEL.items()}


def _labeled_key(conf_key: str) -> str:
    """返回中文标签作为 schema key，HA 不翻译时直接显示中文。"""
    return _LABEL.get(conf_key, conf_key)


def _remap_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """将中文 key 映射回 CONF_* 常量 key。"""
    return {_label_to_key.get(k, k): v for k, v in user_input.items()}


class BambuAIMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bambu AI Print Monitor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str | None = None
        self._access_code: str | None = None
        self._serial: str | None = None
        self._printer_model: str | None = None
        self._camera_port: int | None = None
        self._yolo_model_path: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — printer config + inference server."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # 中文 key → CONF_* key
            user_input = _remap_input(user_input)

            host = user_input[CONF_HOST]
            access_code = user_input[CONF_ACCESS_CODE]
            serial = user_input.get(CONF_SERIAL, "")
            printer_model = user_input[CONF_PRINTER_MODEL]
            camera_port = user_input.get(CONF_CAMERA_PORT, DEFAULT_CAMERA_PORT)
            yolo_model_path = user_input.get(CONF_YOLO_MODEL_PATH, DEFAULT_YOLO_MODEL_PATH)
            inference_host = user_input.get(CONF_INFERENCE_HOST, DEFAULT_INFERENCE_HOST)
            inference_port = user_input.get(CONF_INFERENCE_PORT, DEFAULT_INFERENCE_PORT)

            # Test printer connection
            connected = await self._test_printer_connection(host, access_code)
            if not connected:
                errors["base"] = "cannot_connect"
            else:
                self._host = host
                self._access_code = access_code
                self._serial = serial
                self._printer_model = printer_model
                self._camera_port = camera_port
                self._yolo_model_path = yolo_model_path

                data = {
                    CONF_HOST: host,
                    CONF_ACCESS_CODE: access_code,
                    CONF_SERIAL: serial,
                    CONF_PRINTER_MODEL: printer_model,
                    CONF_CAMERA_PORT: camera_port,
                    CONF_YOLO_MODEL_PATH: yolo_model_path,
                    CONF_INFERENCE_HOST: inference_host,
                    CONF_INFERENCE_PORT: inference_port,
                }

                await self.async_set_unique_id(
                    f"bambu_{host}_{serial}"
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Bambu {printer_model} ({host})",
                    data=data,
                    options={
                        CONF_ANALYSIS_INTERVAL: DEFAULT_ANALYSIS_INTERVAL,
                        CONF_CONFIDENCE_THRESHOLD: DEFAULT_CONFIDENCE_THRESHOLD,
                        CONF_AUTO_PAUSE: DEFAULT_AUTO_PAUSE,
                        CONF_CONSECUTIVE_DETECTIONS: DEFAULT_CONSECUTIVE_DETECTIONS,
                        CONF_INFERENCE_HOST: inference_host,
                        CONF_INFERENCE_PORT: inference_port,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(_labeled_key(CONF_HOST)): str,
                    vol.Required(_labeled_key(CONF_ACCESS_CODE)): str,
                    vol.Optional(_labeled_key(CONF_SERIAL), default=""): str,
                    vol.Required(_labeled_key(CONF_PRINTER_MODEL)): vol.In(
                        {m.value: m.value for m in PrinterModel}
                    ),
                    vol.Optional(
                        _labeled_key(CONF_CAMERA_PORT), default=DEFAULT_CAMERA_PORT
                    ): int,
                    vol.Optional(
                        _labeled_key(CONF_YOLO_MODEL_PATH),
                        default=DEFAULT_YOLO_MODEL_PATH,
                    ): str,
                    vol.Optional(
                        _labeled_key(CONF_INFERENCE_HOST),
                        default=DEFAULT_INFERENCE_HOST,
                    ): str,
                    vol.Optional(
                        _labeled_key(CONF_INFERENCE_PORT),
                        default=DEFAULT_INFERENCE_PORT,
                    ): int,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _remap_input(user_input)

            host = user_input[CONF_HOST]
            access_code = user_input[CONF_ACCESS_CODE]
            serial = user_input.get(CONF_SERIAL, entry.data.get(CONF_SERIAL, ""))
            printer_model = user_input[CONF_PRINTER_MODEL]
            camera_port = user_input.get(CONF_CAMERA_PORT, DEFAULT_CAMERA_PORT)
            inference_host = user_input.get(
                CONF_INFERENCE_HOST,
                entry.data.get(CONF_INFERENCE_HOST, DEFAULT_INFERENCE_HOST),
            )
            inference_port = user_input.get(
                CONF_INFERENCE_PORT,
                entry.data.get(CONF_INFERENCE_PORT, DEFAULT_INFERENCE_PORT),
            )

            connected = await self._test_printer_connection(host, access_code)
            if not connected:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: host,
                        CONF_ACCESS_CODE: access_code,
                        CONF_SERIAL: serial,
                        CONF_PRINTER_MODEL: printer_model,
                        CONF_CAMERA_PORT: camera_port,
                        CONF_INFERENCE_HOST: inference_host,
                        CONF_INFERENCE_PORT: inference_port,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        _labeled_key(CONF_HOST), default=entry.data[CONF_HOST]
                    ): str,
                    vol.Required(
                        _labeled_key(CONF_ACCESS_CODE),
                        default=entry.data[CONF_ACCESS_CODE],
                    ): str,
                    vol.Optional(
                        _labeled_key(CONF_SERIAL),
                        default=entry.data.get(CONF_SERIAL, ""),
                    ): str,
                    vol.Required(
                        _labeled_key(CONF_PRINTER_MODEL),
                        default=entry.data[CONF_PRINTER_MODEL],
                    ): vol.In({m.value: m.value for m in PrinterModel}),
                    vol.Optional(
                        _labeled_key(CONF_CAMERA_PORT),
                        default=entry.data.get(
                            CONF_CAMERA_PORT, DEFAULT_CAMERA_PORT
                        ),
                    ): int,
                    vol.Optional(
                        _labeled_key(CONF_INFERENCE_HOST),
                        default=entry.data.get(
                            CONF_INFERENCE_HOST, DEFAULT_INFERENCE_HOST
                        ),
                    ): str,
                    vol.Optional(
                        _labeled_key(CONF_INFERENCE_PORT),
                        default=entry.data.get(
                            CONF_INFERENCE_PORT, DEFAULT_INFERENCE_PORT
                        ),
                    ): int,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigFlow,
    ) -> BambuAIMonitorOptionsFlow:
        """Get the options flow for this handler."""
        return BambuAIMonitorOptionsFlow()

    async def _test_printer_connection(
        self, host: str, access_code: str
    ) -> bool:
        """Test connection to Bambu printer via MQTT."""
        from .bambu.mock_client import is_mock_mode
        if is_mock_mode(host, access_code):
            _LOGGER.info("DEBUG MODE: Skipping real printer connection test")
            return True

        try:
            from .bambu.client import BambuLanClient
            client = BambuLanClient(host, access_code)
            result = await client.async_test_connection()
            await client.async_disconnect()
            return result
        except Exception:
            _LOGGER.exception("Error testing printer connection")
            return False


class BambuAIMonitorOptionsFlow(OptionsFlow):
    """Handle options flow for Bambu AI Print Monitor."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options (analysis + inference server)."""
        if user_input is not None:
            user_input = _remap_input(user_input)
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        _labeled_key(CONF_ANALYSIS_INTERVAL),
                        default=self.config_entry.options.get(
                            CONF_ANALYSIS_INTERVAL, DEFAULT_ANALYSIS_INTERVAL
                        ),
                    ): vol.In(
                        {
                            k: f"{v} ({k}s)"
                            for k, v in {
                                30: "30秒",
                                60: "1分钟",
                                300: "5分钟",
                                600: "10分钟",
                                1800: "30分钟",
                            }.items()
                        }
                    ),
                    vol.Required(
                        _labeled_key(CONF_CONFIDENCE_THRESHOLD),
                        default=self.config_entry.options.get(
                            CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1.0)),
                    vol.Required(
                        _labeled_key(CONF_AUTO_PAUSE),
                        default=self.config_entry.options.get(
                            CONF_AUTO_PAUSE, DEFAULT_AUTO_PAUSE
                        ),
                    ): bool,
                    vol.Required(
                        _labeled_key(CONF_CONSECUTIVE_DETECTIONS),
                        default=self.config_entry.options.get(
                            CONF_CONSECUTIVE_DETECTIONS,
                            DEFAULT_CONSECUTIVE_DETECTIONS,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
                    vol.Optional(
                        _labeled_key(CONF_INFERENCE_HOST),
                        default=self.config_entry.options.get(
                            CONF_INFERENCE_HOST,
                            self.config_entry.data.get(
                                CONF_INFERENCE_HOST, DEFAULT_INFERENCE_HOST
                            ),
                        ),
                    ): str,
                    vol.Optional(
                        _labeled_key(CONF_INFERENCE_PORT),
                        default=self.config_entry.options.get(
                            CONF_INFERENCE_PORT,
                            self.config_entry.data.get(
                                CONF_INFERENCE_PORT, DEFAULT_INFERENCE_PORT
                            ),
                        ),
                    ): int,
                }
            ),
        )
