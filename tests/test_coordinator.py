"""Coordinator behavior tests for FusionSolar integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.huawei_fusionsolar.coordinator import FusionSolarDataUpdateCoordinator
from custom_components.huawei_fusionsolar.fusion_solar_api import (
    CannotConnect,
    InvalidAuth,
    PlantInfo,
    PlantSnapshot,
)


@dataclass(slots=True)
class FakeEntry:
    """Minimal ConfigEntry subset used by the coordinator."""

    entry_id: str
    data: dict
    options: dict


class FakeHass:
    """Minimal HomeAssistant object with loop reference."""

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()


class FakeApi:
    """Simple API stub for coordinator tests."""

    def __init__(self, plants: list[PlantInfo], metric_map: dict[str, PlantSnapshot | Exception]):
        self._plants = plants
        self._metric_map = metric_map

    def set_timeout_seconds(self, timeout_seconds: int) -> None:
        return None

    def set_preferred_host(self, host: str | None) -> None:
        return None

    async def async_get_plants(self) -> list[PlantInfo]:
        if isinstance(self._plants, Exception):
            raise self._plants
        return self._plants

    async def async_get_metrics(self, plant_id: str) -> PlantSnapshot:
        result = self._metric_map[plant_id]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.asyncio
async def test_coordinator_keeps_previous_snapshot_on_partial_failure() -> None:
    """If one plant fails, previous data for that plant should be preserved."""
    now = datetime.now(UTC)
    plants = [
        PlantInfo("plant-001", "Casa Norte"),
        PlantInfo("plant-002", "Casa Sur"),
    ]

    old_snapshot = PlantSnapshot(
        plant_id="plant-002",
        plant_name="Casa Sur",
        power_w=1500,
        energy_today_kwh=5,
        energy_month_kwh=70,
        energy_year_kwh=300,
        energy_total_kwh=2400,
        updated_at_utc=now,
    )

    new_snapshot = PlantSnapshot(
        plant_id="plant-001",
        plant_name="Casa Norte",
        power_w=3200,
        energy_today_kwh=12,
        energy_month_kwh=200,
        energy_year_kwh=1100,
        energy_total_kwh=8000,
        updated_at_utc=now,
    )

    api = FakeApi(
        plants=plants,
        metric_map={
            "plant-001": new_snapshot,
            "plant-002": CannotConnect("timeout"),
        },
    )
    entry = FakeEntry(
        entry_id="entry-1",
        data={},
        options={},
    )

    coordinator = FusionSolarDataUpdateCoordinator(FakeHass(), entry, api)
    coordinator.data = {"plant-002": old_snapshot}

    data = await coordinator._async_update_data()

    assert data["plant-001"] == new_snapshot
    assert data["plant-002"] == old_snapshot


@pytest.mark.asyncio
async def test_coordinator_raises_reauth_on_invalid_auth() -> None:
    """Invalid auth from API should trigger Home Assistant reauth flow."""
    api = FakeApi(plants=InvalidAuth("bad creds"), metric_map={})
    entry = FakeEntry(entry_id="entry-2", data={}, options={})
    coordinator = FusionSolarDataUpdateCoordinator(FakeHass(), entry, api)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
