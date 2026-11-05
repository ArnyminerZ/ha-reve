"""The Reve EV charger integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .api import ReveApi
from .const import CONF_API_KEY, CONF_EVSE_ID, DOMAIN, SUBENTRY_TYPE_CHARGER
from .coordinator import ReveCoordinator
from .entity import register_charger_devices

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]

type ReveConfigEntry = ConfigEntry[ReveCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ReveConfigEntry) -> bool:
    """Set up Reve from a config entry (the API key "gateway")."""
    api = ReveApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = ReveCoordinator(hass, entry, api)
    await coordinator.async_load_watches()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_shutdown_watches)

    # Adding / removing a charger subentry reloads the entry.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    register_charger_devices(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ReveConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ReveConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ReveConfigEntry, device: DeviceEntry
) -> bool:
    """Allow removing devices of chargers that are no longer configured."""
    configured = {
        s.data[CONF_EVSE_ID]
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_TYPE_CHARGER
    }
    return not any(
        domain == DOMAIN and ident.split("_conn_")[0] in configured
        for domain, ident in device.identifiers
    )
