"""Sensor platform for Huawei FusionSolar."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FusionSolarRuntimeData
from .const import DOMAIN
from .coordinator import FusionSolarDataUpdateCoordinator
from .fusion_solar_api import PlantSnapshot


@dataclass(frozen=True, kw_only=True)
class FusionSolarSensorDescription(SensorEntityDescription):
    """Describe FusionSolar sensor entity."""

    value_fn: Callable[[PlantSnapshot], float]


SENSOR_DESCRIPTIONS: Final[tuple[FusionSolarSensorDescription, ...]] = (
    FusionSolarSensorDescription(
        key="power_w",
        translation_key="power_w",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda snapshot: snapshot.power_w,
    ),
    FusionSolarSensorDescription(
        key="energy_today_kwh",
        translation_key="energy_today_kwh",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda snapshot: snapshot.energy_today_kwh,
    ),
    FusionSolarSensorDescription(
        key="energy_month_kwh",
        translation_key="energy_month_kwh",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda snapshot: snapshot.energy_month_kwh,
    ),
    FusionSolarSensorDescription(
        key="energy_year_kwh",
        translation_key="energy_year_kwh",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda snapshot: snapshot.energy_year_kwh,
    ),
    FusionSolarSensorDescription(
        key="energy_total_kwh",
        translation_key="energy_total_kwh",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda snapshot: snapshot.energy_total_kwh,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FusionSolar sensor entities from config entry."""
    runtime: FusionSolarRuntimeData = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinator

    entities: dict[str, FusionSolarSensor] = {}

    def _collect_new_entities() -> list[FusionSolarSensor]:
        new_entities: list[FusionSolarSensor] = []
        for plant_id in coordinator.data:
            for description in SENSOR_DESCRIPTIONS:
                unique_id = f"{plant_id}_{description.key}"
                if unique_id in entities:
                    continue

                entity = FusionSolarSensor(
                    coordinator=coordinator,
                    plant_id=plant_id,
                    description=description,
                )
                entities[unique_id] = entity
                new_entities.append(entity)

        return new_entities

    initial_entities = _collect_new_entities()
    if initial_entities:
        async_add_entities(initial_entities)

    @callback
    def _async_add_new_entities() -> None:
        next_entities = _collect_new_entities()
        if next_entities:
            async_add_entities(next_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class FusionSolarSensor(
    CoordinatorEntity[FusionSolarDataUpdateCoordinator],
    SensorEntity,
):
    """Representation of a FusionSolar sensor."""

    entity_description: FusionSolarSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FusionSolarDataUpdateCoordinator,
        plant_id: str,
        description: FusionSolarSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._plant_id = plant_id
        self.entity_description = description
        self._attr_unique_id = f"{plant_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return native value for this sensor."""
        snapshot = self.coordinator.data.get(self._plant_id)
        if not snapshot:
            return None
        return self.entity_description.value_fn(snapshot)

    @property
    def available(self) -> bool:
        """Return availability based on coordinator data."""
        return super().available and self._plant_id in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        """Return metadata for plant device."""
        snapshot = self.coordinator.data.get(self._plant_id)
        plant_name = (
            snapshot.plant_name
            if snapshot
            else self.coordinator.known_plants.get(self._plant_id, self._plant_id)
        )

        return DeviceInfo(
            identifiers={(DOMAIN, self._plant_id)},
            manufacturer="Huawei",
            model="FusionSolar",
            name=plant_name,
        )
