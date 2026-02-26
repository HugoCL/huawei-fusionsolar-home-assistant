"""Data update coordinator for Huawei FusionSolar."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ENABLED_PLANT_IDS,
    CONF_HOST_OVERRIDE,
    CONF_POLL_INTERVAL_SECONDS,
    CONF_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DOMAIN,
    MAX_BACKOFF_SECONDS,
)
from .fusion_solar_api import (
    CannotConnect,
    EndpointSchemaChanged,
    FusionSolarApiClient,
    InvalidAuth,
    PlantSnapshot,
    RateLimited,
)

LOGGER = logging.getLogger(__name__)


class FusionSolarDataUpdateCoordinator(DataUpdateCoordinator[dict[str, PlantSnapshot]]):
    """Handle FusionSolar data updates for one account."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: FusionSolarApiClient,
    ) -> None:
        self.api = api
        self.config_entry = entry
        self._failure_count = 0
        self._last_success_at_utc: datetime | None = None
        self._known_plants: dict[str, str] = {}

        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=self._poll_interval_seconds),
        )

    @property
    def known_plants(self) -> dict[str, str]:
        """Return discovered plants (id -> name)."""
        return dict(self._known_plants)

    @property
    def last_success_at_utc(self) -> datetime | None:
        """Return timestamp of latest successful full update."""
        return self._last_success_at_utc

    @property
    def _poll_interval_seconds(self) -> int:
        value = self.config_entry.options.get(
            CONF_POLL_INTERVAL_SECONDS,
            DEFAULT_POLL_INTERVAL_SECONDS,
        )
        try:
            return max(30, int(value))
        except (TypeError, ValueError):
            return DEFAULT_POLL_INTERVAL_SECONDS

    @property
    def _request_timeout_seconds(self) -> int:
        value = self.config_entry.options.get(
            CONF_REQUEST_TIMEOUT_SECONDS,
            DEFAULT_TIMEOUT_SECONDS,
        )
        try:
            return max(5, int(value))
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_SECONDS

    @property
    def _enabled_plant_ids(self) -> set[str]:
        enabled = self.config_entry.options.get(CONF_ENABLED_PLANT_IDS)
        if not enabled:
            return set()
        return {str(plant_id) for plant_id in enabled}

    def _apply_backoff(self) -> None:
        self._failure_count += 1
        next_seconds = min(
            MAX_BACKOFF_SECONDS,
            self._poll_interval_seconds * (2**self._failure_count),
        )
        self.update_interval = timedelta(seconds=next_seconds)

    def _clear_backoff(self) -> None:
        self._failure_count = 0
        self.update_interval = timedelta(seconds=self._poll_interval_seconds)

    async def _async_update_data(self) -> dict[str, PlantSnapshot]:
        """Fetch data from FusionSolar and normalize it."""
        self.api.set_timeout_seconds(self._request_timeout_seconds)
        self.api.set_preferred_host(
            self.config_entry.options.get(CONF_HOST_OVERRIDE)
            or self.config_entry.data.get(CONF_HOST_OVERRIDE)
        )

        try:
            plants = await self.api.async_get_plants()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except RateLimited as err:
            self._apply_backoff()
            raise UpdateFailed("FusionSolar rate-limited the request") from err
        except CannotConnect as err:
            self._apply_backoff()
            raise UpdateFailed("Cannot connect to FusionSolar") from err
        except EndpointSchemaChanged as err:
            raise UpdateFailed("FusionSolar endpoint schema changed") from err

        if not plants:
            raise UpdateFailed("No plants returned by FusionSolar")

        self._known_plants = {plant.plant_id: plant.plant_name for plant in plants}
        enabled_plant_ids = self._enabled_plant_ids
        selected_plants = [
            plant
            for plant in plants
            if not enabled_plant_ids or plant.plant_id in enabled_plant_ids
        ]

        if not selected_plants:
            raise UpdateFailed("No plants selected for polling")

        results = await asyncio.gather(
            *(self.api.async_get_metrics(plant.plant_id) for plant in selected_plants),
            return_exceptions=True,
        )

        previous_data = self.data if isinstance(self.data, dict) else {}
        snapshots: dict[str, PlantSnapshot] = {}
        partial_errors: list[tuple[str, Exception]] = []

        for plant, result in zip(selected_plants, results, strict=True):
            if isinstance(result, Exception):
                if isinstance(result, InvalidAuth):
                    raise ConfigEntryAuthFailed from result

                partial_errors.append((plant.plant_id, result))
                if plant.plant_id in previous_data:
                    snapshots[plant.plant_id] = previous_data[plant.plant_id]
                continue

            if not result.plant_name:
                result = PlantSnapshot(
                    plant_id=result.plant_id,
                    plant_name=plant.plant_name,
                    power_w=result.power_w,
                    energy_today_kwh=result.energy_today_kwh,
                    energy_month_kwh=result.energy_month_kwh,
                    energy_year_kwh=result.energy_year_kwh,
                    energy_total_kwh=result.energy_total_kwh,
                    updated_at_utc=result.updated_at_utc,
                )

            snapshots[plant.plant_id] = result

        if not snapshots:
            self._apply_backoff()
            raise UpdateFailed("All plant requests failed")

        if partial_errors:
            error_summary = ", ".join(
                f"{plant_id}:{type(err).__name__}" for plant_id, err in partial_errors
            )
            LOGGER.warning("Partial FusionSolar update failure: %s", error_summary)

        self._last_success_at_utc = datetime.now(UTC)
        self._clear_backoff()
        return snapshots

    def diagnostics_payload(self) -> dict[str, Any]:
        """Return coordinator state useful for diagnostics."""
        return {
            "failure_count": self._failure_count,
            "update_interval_seconds": int(self.update_interval.total_seconds()),
            "known_plants": self._known_plants,
            "last_success_at_utc": (
                self._last_success_at_utc.isoformat()
                if self._last_success_at_utc
                else None
            ),
        }
