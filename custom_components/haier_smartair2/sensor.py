"""Sensor platform: room temperature per device."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HaierConfigEntry
from .const import DOMAIN
from .coordinator import HaierCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: HaierConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up temperature sensors."""
    async_add_entities(
        HaierRoomTemp(coord) for coord in entry.runtime_data.coordinators
    )


class HaierRoomTemp(CoordinatorEntity[HaierCoordinator], SensorEntity):
    """Room temperature reported by the AC."""

    _attr_has_entity_name = True
    _attr_translation_key = "room_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: HaierCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{coordinator.devid}_room_temp"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.devid)})

    @property
    def native_value(self) -> float | None:
        return getattr(self.coordinator.data, "current_temp", None)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and getattr(self.coordinator.data, "current_temp", None) is not None
        )
