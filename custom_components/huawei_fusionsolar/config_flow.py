"""Config flow for Huawei FusionSolar integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ENABLED_PLANT_IDS,
    CONF_HOST_OVERRIDE,
    CONF_PLANT_INDEX,
    CONF_POLL_INTERVAL_SECONDS,
    CONF_REQUEST_TIMEOUT_SECONDS,
    CONF_VERIFY_SSL,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .fusion_solar_api import (
    CannotConnect,
    EndpointSchemaChanged,
    FusionSolarApiClient,
    InvalidAuth,
    RateLimited,
)


def _normalize_host(host: str | None) -> str | None:
    if not host:
        return None
    return host.strip().lower().replace("https://", "").replace("http://", "").rstrip("/")


async def _async_validate_input(
    hass: HomeAssistant,
    user_input: dict[str, Any],
) -> dict[str, Any]:
    """Validate user credentials and discover plants."""
    verify_ssl = user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)

    client = FusionSolarApiClient(
        session,
        username=user_input[CONF_USERNAME],
        password=user_input[CONF_PASSWORD],
        preferred_host=_normalize_host(user_input.get(CONF_HOST_OVERRIDE)),
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        verify_ssl=verify_ssl,
    )

    await client.async_login()
    plants = await client.async_get_plants()
    if not plants:
        raise CannotConnect("No plants available")

    return {
        "effective_host": client.effective_host,
        "plant_index": {plant.plant_id: plant.plant_name for plant in plants},
    }


class FusionSolarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Huawei FusionSolar."""

    VERSION = 1

    _reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle user setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_HOST_OVERRIDE] = _normalize_host(
                user_input.get(CONF_HOST_OVERRIDE)
            )

            try:
                validated = await _async_validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except RateLimited:
                errors["base"] = "rate_limited"
            except EndpointSchemaChanged:
                errors["base"] = "endpoint_schema_changed"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pragma: no cover - defensive
                errors["base"] = "unknown"
            else:
                unique_id = (
                    f"{user_input[CONF_USERNAME].strip().lower()}"
                    f"@{validated['effective_host']}"
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                plant_index = validated["plant_index"]
                data = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_HOST_OVERRIDE: user_input.get(CONF_HOST_OVERRIDE),
                    CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                    CONF_PLANT_INDEX: plant_index,
                }
                options = {
                    CONF_POLL_INTERVAL_SECONDS: DEFAULT_POLL_INTERVAL_SECONDS,
                    CONF_REQUEST_TIMEOUT_SECONDS: DEFAULT_TIMEOUT_SECONDS,
                    CONF_ENABLED_PLANT_IDS: list(plant_index.keys()),
                }

                return self.async_create_entry(
                    title=f"FusionSolar ({user_input[CONF_USERNAME]})",
                    data=data,
                    options=options,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_HOST_OVERRIDE, default=""): str,
                    vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Start reauth flow."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Reauthenticate existing entry with fresh credentials."""
        assert self._reauth_entry is not None

        errors: dict[str, str] = {}

        if user_input is not None:
            payload = {
                CONF_USERNAME: self._reauth_entry.data[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_HOST_OVERRIDE: _normalize_host(
                    user_input.get(
                        CONF_HOST_OVERRIDE,
                        self._reauth_entry.data.get(CONF_HOST_OVERRIDE),
                    )
                ),
                CONF_VERIFY_SSL: self._reauth_entry.data.get(
                    CONF_VERIFY_SSL,
                    DEFAULT_VERIFY_SSL,
                ),
            }

            try:
                validated = await _async_validate_input(self.hass, payload)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except RateLimited:
                errors["base"] = "rate_limited"
            except EndpointSchemaChanged:
                errors["base"] = "endpoint_schema_changed"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pragma: no cover - defensive
                errors["base"] = "unknown"
            else:
                updated_data = {
                    **self._reauth_entry.data,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_HOST_OVERRIDE: payload.get(CONF_HOST_OVERRIDE),
                    CONF_PLANT_INDEX: validated["plant_index"],
                }

                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data=updated_data,
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(
                        CONF_HOST_OVERRIDE,
                        default=self._reauth_entry.data.get(CONF_HOST_OVERRIDE) or "",
                    ): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return FusionSolarOptionsFlow(entry)


class FusionSolarOptionsFlow(config_entries.OptionsFlow):
    """Handle options for FusionSolar integration."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            options = {
                CONF_POLL_INTERVAL_SECONDS: int(
                    user_input[CONF_POLL_INTERVAL_SECONDS]
                ),
                CONF_REQUEST_TIMEOUT_SECONDS: int(
                    user_input[CONF_REQUEST_TIMEOUT_SECONDS]
                ),
                CONF_HOST_OVERRIDE: _normalize_host(user_input.get(CONF_HOST_OVERRIDE)),
            }

            enabled = user_input.get(CONF_ENABLED_PLANT_IDS)
            if isinstance(enabled, dict):
                enabled = [key for key, selected in enabled.items() if selected]
            if enabled is not None:
                options[CONF_ENABLED_PLANT_IDS] = list(enabled)

            return self.async_create_entry(title="", data=options)

        plant_index = self.entry.data.get(CONF_PLANT_INDEX, {})
        enabled_default = self.entry.options.get(
            CONF_ENABLED_PLANT_IDS,
            list(plant_index.keys()),
        )

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_POLL_INTERVAL_SECONDS,
                default=self.entry.options.get(
                    CONF_POLL_INTERVAL_SECONDS,
                    DEFAULT_POLL_INTERVAL_SECONDS,
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
            vol.Required(
                CONF_REQUEST_TIMEOUT_SECONDS,
                default=self.entry.options.get(
                    CONF_REQUEST_TIMEOUT_SECONDS,
                    DEFAULT_TIMEOUT_SECONDS,
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
            vol.Optional(
                CONF_HOST_OVERRIDE,
                default=self.entry.options.get(CONF_HOST_OVERRIDE)
                or self.entry.data.get(CONF_HOST_OVERRIDE)
                or "",
            ): str,
        }

        if plant_index:
            schema[
                vol.Optional(
                    CONF_ENABLED_PLANT_IDS,
                    default=enabled_default,
                )
            ] = cv.multi_select(plant_index)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
        )
