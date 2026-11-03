"""Switch platform: health, display and 10 °C heat (V3 extras only)."""

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

SWITCH_KEYS = ("health", "display", "heat10")


async def async_setup_entry(
    hass: HomeAssistant, entry: HaierConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up V3 extra switches."""
    async_add_entities(
        HaierV3Switch(coord, key)
        for coord in entry.runtime_data.coordinators
        if coord.v3_extras
        for key in SWITCH_KEYS
    )


class HaierV3Switch(CoordinatorEntity[HaierCoordinator], SwitchEntity):
    """A boolean V3 control."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HaierCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{DOMAIN}_{coordinator.devid}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.devid)})

    @property
    def is_on(self) -> bool | None:
        return getattr(self.coordinator.data, self._key, None)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_apply(**{self._key: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_apply(**{self._key: False})
