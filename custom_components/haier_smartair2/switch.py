"""Switch platform for Haier SmartAir2 (Health mode)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up Haier SmartAir2 switches."""
    async_add_entities(
        HaierHealthSwitch(coord)
        for coord in entry.runtime_data.coordinators
        if coord.codec.supports_health
    )


class HaierHealthSwitch(CoordinatorEntity[HaierCoordinator], SwitchEntity):
    """Health mode (UV-C / ionizer) switch for a Haier air conditioner."""

    _attr_has_entity_name = True
    _attr_translation_key = "health"
    _attr_name = "Health"
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, coordinator: HaierCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{coordinator.devid}_health"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.devid)})

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return bool(self.coordinator.data.health)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_apply(health=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_apply(health=False)
