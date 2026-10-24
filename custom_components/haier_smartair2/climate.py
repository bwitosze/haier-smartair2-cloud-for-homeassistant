"""Climate platform for Haier SmartAir2."""

from __future__ import annotations

from homeassistant.components.climate import (
    SWING_OFF,
    SWING_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HaierConfigEntry
from .const import (
    DOMAIN,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MID,
    MAX_TEMP,
    MIN_TEMP,
    MODE_AUTO,
    MODE_COOL,
    MODE_DRY,
    MODE_FAN,
    MODE_HEAT,
    TEMP_STEP,
)
from .coordinator import HaierCoordinator

MODE_TO_HVAC = {
    MODE_AUTO: HVACMode.AUTO,
    MODE_COOL: HVACMode.COOL,
    MODE_HEAT: HVACMode.HEAT,
    MODE_FAN: HVACMode.FAN_ONLY,
    MODE_DRY: HVACMode.DRY,
}
HVAC_TO_MODE = {v: k for k, v in MODE_TO_HVAC.items()}

FAN_TO_HA = {FAN_AUTO: "auto", FAN_LOW: "low", FAN_MID: "medium", FAN_HIGH: "high"}
HA_TO_FAN = {v: k for k, v in FAN_TO_HA.items()}

# Vertical louvre only. Haier's device profile also defines a left/right flag
# (20200J, word 8 bit 1), but this unit has no horizontal louvre to drive with it
# — exposing it just added a control that never did anything. See codec.py.
SWING_BOOL = [SWING_OFF, SWING_ON]


async def async_setup_entry(
    hass: HomeAssistant, entry: HaierConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up climate entities."""
    async_add_entities(
        HaierClimate(coord) for coord in entry.runtime_data.coordinators
    )


class HaierClimate(CoordinatorEntity[HaierCoordinator], ClimateEntity):
    """A Haier air conditioner."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = TEMP_STEP
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.AUTO,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: HaierCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{coordinator.devid}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.devid)},
            name=coordinator.dev_name,
            manufacturer="Haier",
            model="SmartAir2 (cloud)" if coordinator.via_cloud else "SmartAir2 (local)",
        )
        # fan selector only when the codec reliably supports fan control
        # (V2: auto/quiet/low/medium/high/turbo; V3: same minus turbo, which this
        # generation does not expose)
        if coordinator.codec.supports_fan:
            extras = coordinator.codec.extra_fan_modes
            modes = ["auto"]
            if "quiet" in extras:
                modes.append("quiet")
            modes += ["low", "medium", "high"]
            if "turbo" in extras:
                modes.append("turbo")
            self._attr_fan_modes = modes
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
        # Swing selector only on generations where the louvre bits are known.
        # V2 (salon) has them straight from Haier's device profile; V3 (maks) was
        # never calibrated — and that unit's louvre is mechanically damaged, so it
        # must stay unexposed rather than merely untested.
        if coordinator.codec.supports_swing:
            self._attr_swing_modes = SWING_BOOL
            self._attr_supported_features |= ClimateEntityFeature.SWING_MODE

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def current_temperature(self) -> float | None:
        return getattr(self.coordinator.data, "current_temp", None)

    @property
    def target_temperature(self) -> float | None:
        return getattr(self.coordinator.data, "target_temp", None)

    @property
    def hvac_mode(self) -> HVACMode | None:
        st = self.coordinator.data
        if st is None:
            return None
        if st.power is False:
            return HVACMode.OFF
        return MODE_TO_HVAC.get(st.mode, HVACMode.AUTO)

    @property
    def fan_mode(self) -> str | None:
        st = self.coordinator.data
        if st is None:
            return None
        if st.quiet:
            return "quiet"
        if st.turbo:
            return "turbo"
        return FAN_TO_HA.get(st.fan)

    @property
    def swing_mode(self) -> str | None:
        """Up/down louvre (20200I)."""
        if self.coordinator.data is None or not self.coordinator.codec.supports_swing:
            return None
        return SWING_ON if self.coordinator.data.swing_v else SWING_OFF

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        # deliberately no power=True: moving the louvre should not switch a
        # sleeping unit on, unlike a temperature or mode change
        await self.coordinator.async_apply(swing_v=swing_mode == SWING_ON)

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.coordinator.async_apply(target_temp=float(temp), power=True)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_apply(power=False)
        else:
            mode = HVAC_TO_MODE.get(hvac_mode, MODE_AUTO)
            await self.coordinator.async_apply(power=True, mode=mode)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode == "quiet":
            await self.coordinator.async_apply(quiet=True, turbo=False, power=True)
        elif fan_mode == "turbo":
            await self.coordinator.async_apply(turbo=True, quiet=False, power=True)
        else:
            fan = HA_TO_FAN.get(fan_mode)
            if fan is not None:
                await self.coordinator.async_apply(
                    fan=fan, quiet=False, turbo=False, power=True
                )

    async def async_turn_on(self) -> None:
        await self.coordinator.async_apply(power=True)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_apply(power=False)
