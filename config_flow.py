"""Config flow for Bambu AI Print Monitor."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACCESS_CODE,
    CONF_AI_API_KEY,
    CONF_ANALYSIS_INTERVAL,
    CONF_ANALYSIS_MODEL,
    CONF_AUTO_PAUSE,
    CONF_CAMERA_PORT,
    CONF_CONFIDENCE_THRESHOLD,
    CONF_CONSECUTIVE_DETECTIONS,
    CONF_PRINTER_MODEL,
    CONF_SERIAL,
    DEFAULT_ANALYSIS_INTERVAL,
    DEFAULT_ANALYSIS_MODEL,
    DEFAULT_AUTO_PAUSE,
    DEFAULT_CAMERA_PORT,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_CONSECUTIVE_DETECTIONS,
    DEFAULT_MQTT_PORT,
    AI_MODELS,
    AI_PROVIDER_NAME,
    DOMAIN,
    PrinterModel,
)

_LOGGER = logging.getLogger(__name__)


class BambuAIMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bambu AI Print Monitor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._host: str | None = None
        self._access_code: str | None = None
        self._serial: str | None = None
        self._printer_model: str | None = None
        self._camera_port: int | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._access_code = user_input[CONF_ACCESS_CODE]
            self._serial = user_input.get(CONF_SERIAL, "")
            self._printer_model = user_input[CONF_PRINTER_MODEL]
            self._camera_port = user_input.get(CONF_CAMERA_PORT, DEFAULT_CAMERA_PORT)

            # Test printer connection
            connected = await self._test_printer_connection(
                self._host, self._access_code
            )
            if not connected:
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_ai_config()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_ACCESS_CODE): str,
                    vol.Optional(CONF_SERIAL, default=""): str,
                    vol.Required(CONF_PRINTER_MODEL): vol.In(
                        {m.value: m.value for m in PrinterModel}
                    ),
                    vol.Optional(CONF_CAMERA_PORT, default=DEFAULT_CAMERA_PORT): int,
                }
            ),
            errors=errors,
        )

    async def async_step_ai_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle AI API key step."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_AI_API_KEY]
            model = user_input.get(CONF_ANALYSIS_MODEL, DEFAULT_ANALYSIS_MODEL)

            # Test AI API key
            valid, error_msg = await self._test_ai_api_key(api_key, model)
            if not valid:
                _LOGGER.warning("AI API validation failed: %s", error_msg)
                placeholders["detail"] = error_msg or "未知错误"
                errors["base"] = "invalid_api_key"
            else:
                self._data = {
                    CONF_HOST: self._host,
                    CONF_ACCESS_CODE: self._access_code,
                    CONF_SERIAL: self._serial,
                    CONF_PRINTER_MODEL: self._printer_model,
                    CONF_CAMERA_PORT: self._camera_port,
                    CONF_AI_API_KEY: api_key,
                    CONF_ANALYSIS_MODEL: model,
                }

                # Check for duplicate entries
                await self.async_set_unique_id(
                    f"bambu_{self._host}_{self._serial}"
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Bambu {self._printer_model} ({self._host})",
                    data=self._data,
                    options={
                        CONF_ANALYSIS_INTERVAL: DEFAULT_ANALYSIS_INTERVAL,
                        CONF_CONFIDENCE_THRESHOLD: DEFAULT_CONFIDENCE_THRESHOLD,
                        CONF_AUTO_PAUSE: DEFAULT_AUTO_PAUSE,
                        CONF_CONSECUTIVE_DETECTIONS: DEFAULT_CONSECUTIVE_DETECTIONS,
                    },
                )

        return self.async_show_form(
            step_id="ai_config",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AI_API_KEY): str,
                    vol.Optional(
                        CONF_ANALYSIS_MODEL, default=DEFAULT_ANALYSIS_MODEL
                    ): vol.In(AI_MODELS),
                }
            ),
            description_placeholders=placeholders or None,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._access_code = user_input[CONF_ACCESS_CODE]
            self._serial = user_input.get(CONF_SERIAL, entry.data.get(CONF_SERIAL, ""))
            self._printer_model = user_input[CONF_PRINTER_MODEL]
            self._camera_port = user_input.get(CONF_CAMERA_PORT, DEFAULT_CAMERA_PORT)

            connected = await self._test_printer_connection(
                self._host, self._access_code
            )
            if not connected:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: self._host,
                        CONF_ACCESS_CODE: self._access_code,
                        CONF_SERIAL: self._serial,
                        CONF_PRINTER_MODEL: self._printer_model,
                        CONF_CAMERA_PORT: self._camera_port,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Required(
                        CONF_ACCESS_CODE, default=entry.data[CONF_ACCESS_CODE]
                    ): str,
                    vol.Optional(
                        CONF_SERIAL, default=entry.data.get(CONF_SERIAL, "")
                    ): str,
                    vol.Required(
                        CONF_PRINTER_MODEL,
                        default=entry.data[CONF_PRINTER_MODEL],
                    ): vol.In({m.value: m.value for m in PrinterModel}),
                    vol.Optional(
                        CONF_CAMERA_PORT,
                        default=entry.data.get(CONF_CAMERA_PORT, DEFAULT_CAMERA_PORT),
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
        # Check for debug mode
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

    async def _test_ai_api_key(
        self, api_key: str, model: str
    ) -> tuple[bool, str | None]:
        """Test AI API key validity."""
        try:
            from .ai_provider.client import AIClient

            client = AIClient(api_key, model)
            return await client.async_validate_api_key()
        except Exception as err:
            _LOGGER.exception("Error testing AI API key")
            return False, f"测试过程出错: {err}"


class BambuAIMonitorOptionsFlow(OptionsFlow):
    """Handle options flow for Bambu AI Print Monitor."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ANALYSIS_INTERVAL,
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
                        CONF_CONFIDENCE_THRESHOLD,
                        default=self.config_entry.options.get(
                            CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1.0)),
                    vol.Required(
                        CONF_AUTO_PAUSE,
                        default=self.config_entry.options.get(
                            CONF_AUTO_PAUSE, DEFAULT_AUTO_PAUSE
                        ),
                    ): bool,
                    vol.Required(
                        CONF_CONSECUTIVE_DETECTIONS,
                        default=self.config_entry.options.get(
                            CONF_CONSECUTIVE_DETECTIONS,
                            DEFAULT_CONSECUTIVE_DETECTIONS,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
                    vol.Required(
                        CONF_ANALYSIS_MODEL,
                        default=self.config_entry.options.get(
                            CONF_ANALYSIS_MODEL,
                            self.config_entry.data.get(
                                CONF_ANALYSIS_MODEL, DEFAULT_ANALYSIS_MODEL
                            ),
                        ),
                    ): vol.In(AI_MODELS),
                }
            ),
        )
