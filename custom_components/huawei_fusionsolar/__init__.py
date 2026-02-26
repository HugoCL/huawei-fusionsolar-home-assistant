"""Huawei FusionSolar custom integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_HOST_OVERRIDE,
    CONF_REQUEST_TIMEOUT_SECONDS,
    CONF_VERIFY_SSL,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import FusionSolarDataUpdateCoordinator
from .fusion_solar_api import FusionSolarApiClient


@dataclass(slots=True)
class FusionSolarRuntimeData:
    """Runtime references for one config entry."""

    api: FusionSolarApiClient
    coordinator: FusionSolarDataUpdateCoordinator


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up via YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Huawei FusionSolar from a config entry."""
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)

    host_override = entry.options.get(CONF_HOST_OVERRIDE) or entry.data.get(
        CONF_HOST_OVERRIDE
    )

    api = FusionSolarApiClient(
        session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        preferred_host=host_override,
        timeout_seconds=entry.options.get(
            CONF_REQUEST_TIMEOUT_SECONDS,
            DEFAULT_TIMEOUT_SECONDS,
        ),
        verify_ssl=verify_ssl,
    )

    coordinator = FusionSolarDataUpdateCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = FusionSolarRuntimeData(
        api=api,
        coordinator=coordinator,
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
