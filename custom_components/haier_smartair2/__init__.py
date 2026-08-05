"""The Haier SmartAir2 integration (cloud + local hybrid)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .cloud import CloudAuthError, HaierCloudClient
from .codec import codec_for_type
from .const import (
    CONF_CLIENT_ID,
    CONF_LOCAL_IPS,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_USERNAME,
    DEFAULT_REGION,
    PLATFORMS,
    REGIONS,
    generate_client_id,
)
from .coordinator import HaierCoordinator
from .local import HaierLocalClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class HaierData:
    """Runtime data for a config entry."""

    cloud: HaierCloudClient | None = None
    local_clients: list[HaierLocalClient] = field(default_factory=list)
    coordinators: list[HaierCoordinator] = field(default_factory=list)


type HaierConfigEntry = ConfigEntry[HaierData]


def _parse_local_map(raw: str | None) -> dict[str, str]:
    """Parse 'MAC:IP,MAC:IP' -> {normalised MAC: IP}."""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        mac, ip = part.split(":", 1)
        mac = "".join(c for c in mac if c.isalnum()).upper()
        ip = ip.strip()
        if len(mac) == 12 and ip:
            out[mac] = ip
    return out


async def _async_update_listener(hass: HomeAssistant, entry: HaierConfigEntry) -> None:
    """Reload the entry when options change (region / local mapping)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: HaierConfigEntry) -> bool:
    """Set up Haier SmartAir2 from a config entry."""
    conf = {**entry.data, **entry.options}  # options override initial data
    region = conf.get(CONF_REGION, DEFAULT_REGION)
    gateway = REGIONS.get(region, REGIONS[DEFAULT_REGION])
    local_map = _parse_local_map(conf.get(CONF_LOCAL_IPS))

    # per-installation gateway client id (migrate older entries that predate it)
    client_id = entry.data.get(CONF_CLIENT_ID)
    if not client_id:
        client_id = generate_client_id()
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_CLIENT_ID: client_id}
        )

    cloud = HaierCloudClient(
        hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD], gateway, client_id
    )
    try:
        devices = await cloud.async_get_devices()
    except CloudAuthError as err:
        raise ConfigEntryNotReady(f"Haier login failed: {err}") from err
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(f"Haier device list failed: {err}") from err

    if not devices:
        _LOGGER.warning("Haier: no devices returned by the account")

    data = HaierData(cloud=cloud)
    any_cloud = False

    for dev in devices:
        devid = (dev.get("id") or "").upper()
        if not devid:
            continue
        name = dev.get("name") or devid
        codec = codec_for_type(dev.get("type"))
        if devid in local_map:
            local = HaierLocalClient(hass, local_map[devid], devid)
            try:
                await local.async_start()
                await local.async_poll(devid)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Haier local %s (%s) failed, falling back to cloud: %s",
                                name, local_map[devid], err)
                cloud.register_device(devid)
                any_cloud = True
                coord = HaierCoordinator(hass, cloud, codec, devid, name, via_cloud=True)
            else:
                data.local_clients.append(local)
                coord = HaierCoordinator(hass, local, codec, devid, name, via_cloud=False)
        else:
            cloud.register_device(devid)
            any_cloud = True
            coord = HaierCoordinator(hass, cloud, codec, devid, name, via_cloud=True)
        data.coordinators.append(coord)

    if any_cloud:
        try:
            await cloud.async_start()
        except Exception as err:  # noqa: BLE001
            raise ConfigEntryNotReady(f"Haier cloud connect failed: {err}") from err

    # first refresh (best-effort; entities go unavailable if a device is silent)
    for coord in data.coordinators:
        await coord.async_config_entry_first_refresh()

    entry.runtime_data = data
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaierConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = entry.runtime_data
        if data.cloud:
            await data.cloud.async_stop()
        for local in data.local_clients:
            await local.async_stop()
    return unload_ok
