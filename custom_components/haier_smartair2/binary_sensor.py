"""Binary sensor platform: self-clean running state (V3 extras only)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    """Set up the self-clean running sensor."""
    async_add_entities(
        HaierSelfCleanRunning(coord)
        for coord in entry.runtime_data.coordinators
        if coord.v3_extras
    )


class HaierSelfCleanRunning(CoordinatorEntity[HaierCoordinator], BinarySensorEntity):
    """On while the AC runs its self-clean cycle."""

    _attr_has_entity_name = True
    _attr_translation_key = "self_clean"

    def __init__(self, coordinator: HaierCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{coordinator.devid}_self_clean"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.devid)})

    @property
    def is_on(self) -> bool | None:
        return getattr(self.coordinator.data, "self_clean", None)
