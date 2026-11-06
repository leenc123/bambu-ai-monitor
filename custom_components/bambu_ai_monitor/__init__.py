"""The Bambu AI Print Monitor integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    CONF_ANALYSIS_INTERVAL,
    CONF_CONFIDENCE_THRESHOLD,
    CONF_INFERENCE_HOST,
    CONF_INFERENCE_PORT,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_INFERENCE_HOST,
    DEFAULT_INFERENCE_PORT,
    DOMAIN,
    LEGACY_CONFIDENCE_THRESHOLD,
    SERVICE_ANALYZE_NOW,
    SERVICE_SET_ANALYSIS_INTERVAL,
)
from .coordinator import BambuAICoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    "button",
    "switch",
    "select",
    "number",
    "camera",
    "sensor",
    "binary_sensor",
]

type BambuAIConfigEntry = ConfigEntry[BambuAICoordinator]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Bambu AI Print Monitor component."""

    async def handle_analyze_now(call: ServiceCall) -> None:
        """Handle the analyze_now service call."""
        entry_id = call.data.get("entry_id")
        coordinators = hass.data.get(DOMAIN, {})
        if entry_id:
            coordinator = coordinators.get(entry_id)
            if coordinator:
                await coordinator.async_analyze_now()
        else:
            for coordinator in coordinators.values():
                await coordinator.async_analyze_now()

    async def handle_set_analysis_interval(call: ServiceCall) -> None:
        """Handle the set_analysis_interval service call."""
        entry_id = call.data.get("entry_id")
        interval = call.data["interval"]
        coordinators = hass.data.get(DOMAIN, {})
        if entry_id:
            coordinator = coordinators.get(entry_id)
            if coordinator:
                await coordinator.async_set_analysis_interval(interval)
        else:
            for coordinator in coordinators.values():
                await coordinator.async_set_analysis_interval(interval)

    hass.services.async_register(
        DOMAIN, SERVICE_ANALYZE_NOW, handle_analyze_now
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_ANALYSIS_INTERVAL, handle_set_analysis_interval
    )

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: BambuAIConfigEntry) -> bool:
    """Migrate legacy config entries.

    v1 -> v2: lower the confidence threshold from the old default (0.5) to
    the new default (0.35). Only entries still on the exact old default are
    touched, so a user-chosen value is never overwritten.
    """
    if entry.version > 2:
        return False

    if entry.version == 1:
        options = dict(entry.options)
        current = options.get(CONF_CONFIDENCE_THRESHOLD, LEGACY_CONFIDENCE_THRESHOLD)
        try:
            if float(current) == LEGACY_CONFIDENCE_THRESHOLD:
                options[CONF_CONFIDENCE_THRESHOLD] = DEFAULT_CONFIDENCE_THRESHOLD
        except (TypeError, ValueError):
            pass
        hass.config_entries.async_update_entry(
            entry, version=2, options=options
        )
        _LOGGER.info(
            "Migrated %s to config entry version 2 (threshold -> %s)",
            entry.entry_id,
            options.get(CONF_CONFIDENCE_THRESHOLD),
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: BambuAIConfigEntry) -> bool:
    """Set up Bambu AI Print Monitor from a config entry."""
    coordinator = BambuAICoordinator(hass, entry)

    try:
        # Works on every HA version: HA >= 2024.8 also calls this from
        # _async_setup during the first refresh, but it is idempotent.
        await coordinator.async_initialize()
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.error("Setup failed for entry %s: %s", entry.entry_id, err, exc_info=True)
        raise ConfigEntryNotReady(f"Failed to connect to printer: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        _LOGGER.error("Failed to set up platforms for %s", entry.entry_id, exc_info=True)
        await coordinator.async_cleanup()
        hass.data[DOMAIN].pop(entry.entry_id)
        raise ConfigEntryNotReady("Failed to set up entities") from None

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BambuAIConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_cleanup()

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: BambuAIConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow user to delete the device from the device page.

    只要实现这个函数，HA 就会在设备页三点菜单里显示 “删除” 按钮。
    返回 True 即允许删除。
    本集成是单 config entry 对应单个设备 (identifiers={(DOMAIN, serial)})，
    删除 device 后 config entry 还在，重启后设备会重建。
    想彻底移除打印机请再到 集成页面删除对应配置项。
    """
    return True


async def async_update_options(hass: HomeAssistant, entry: BambuAIConfigEntry) -> None:
    """Apply option changes without reloading the whole integration.

    Toggling a switch or dragging the threshold slider must not tear down
    the MQTT connection. Only a change to the inference endpoint requires
    a full reload (the client/server objects have to be rebuilt).
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return

    new_host = entry.options.get(
        CONF_INFERENCE_HOST,
        entry.data.get(CONF_INFERENCE_HOST, DEFAULT_INFERENCE_HOST),
    )
    try:
        new_port = int(entry.options.get(
            CONF_INFERENCE_PORT,
            entry.data.get(CONF_INFERENCE_PORT, DEFAULT_INFERENCE_PORT),
        ))
    except (TypeError, ValueError):
        new_port = DEFAULT_INFERENCE_PORT

    if coordinator.inference_endpoint != (new_host, new_port):
        _LOGGER.info(
            "Inference endpoint changed to %s:%s, reloading entry",
            new_host,
            new_port,
        )
        await hass.config_entries.async_reload(entry.entry_id)
        return

    coordinator.async_apply_options(dict(entry.options))
