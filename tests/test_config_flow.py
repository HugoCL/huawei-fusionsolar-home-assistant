"""Config flow helper tests for FusionSolar integration."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.huawei_fusionsolar import config_flow
from custom_components.huawei_fusionsolar.fusion_solar_api import InvalidAuth, PlantInfo


@pytest.mark.asyncio
async def test_validate_input_returns_effective_host_and_plant_index(monkeypatch) -> None:
    """Validation helper should return normalized plant discovery data."""

    class FakeClient:
        def __init__(self, session, **kwargs) -> None:
            self.effective_host = "la3.fusionsolar.huawei.com"

        async def async_login(self) -> None:
            return None

        async def async_get_plants(self) -> list[PlantInfo]:
            return [PlantInfo("plant-001", "Casa Norte")]

    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass, verify_ssl: object())
    monkeypatch.setattr(config_flow, "FusionSolarApiClient", FakeClient)

    result = await config_flow._async_validate_input(
        hass=object(),
        user_input={
            "username": "user@example.com",
            "password": "secret",
            "host_override": "la5.fusionsolar.huawei.com",
            "verify_ssl": True,
        },
    )

    assert result["effective_host"] == "la3.fusionsolar.huawei.com"
    assert result["plant_index"] == {"plant-001": "Casa Norte"}


@pytest.mark.asyncio
async def test_validate_input_propagates_invalid_auth(monkeypatch) -> None:
    """Validation helper should bubble auth failures for the flow layer."""

    class FakeClient:
        def __init__(self, session, **kwargs) -> None:
            return None

        async def async_login(self) -> None:
            raise InvalidAuth("invalid")

        async def async_get_plants(self) -> list[PlantInfo]:
            return []

    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass, verify_ssl: object())
    monkeypatch.setattr(config_flow, "FusionSolarApiClient", FakeClient)

    with pytest.raises(InvalidAuth):
        await config_flow._async_validate_input(
            hass=object(),
            user_input={
                "username": "user@example.com",
                "password": "secret",
                "verify_ssl": True,
            },
        )
