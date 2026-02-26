"""Diagnostics for Huawei FusionSolar integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import FusionSolarRuntimeData
from .const import DOMAIN

TO_REDACT = {
    CONF_PASSWORD,
    "cookie",
    "cookies",
    "token",
    "csrf",
    "session",
    "authorization",
}


def _mask_username(username: str | None) -> str | None:
    if not username:
        return None
    if len(username) <= 2:
        return "*" * len(username)
    return f"{username[:2]}***{username[-1]}"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    entry_data = dict(entry.data)
    options_data = dict(entry.options)

    username_masked = _mask_username(entry_data.get(CONF_USERNAME))
    if CONF_USERNAME in entry_data:
        entry_data.pop(CONF_USERNAME)

    runtime: FusionSolarRuntimeData | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    runtime_payload: dict[str, Any] = {}
    if runtime is not None:
        runtime_payload = {
            "api": runtime.api.get_debug_state(),
            "coordinator": runtime.coordinator.diagnostics_payload(),
        }

    return {
        "config_entry": async_redact_data(entry_data, TO_REDACT),
        "config_entry_options": async_redact_data(options_data, TO_REDACT),
        "username_masked": username_masked,
        "runtime": async_redact_data(runtime_payload, TO_REDACT),
    }
