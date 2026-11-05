"""The Reve EV charger integration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.event import async_call_later

from .api import ReveApi
from .const import CONF_API_KEY, CONF_EVSE_ID, DOMAIN, SUBENTRY_TYPE_CHARGER
from .coordinator import ReveCoordinator
from .entity import register_charger_devices

RELOAD_DELAY = 3
PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]

CARD_URL = "/reve_static/reve-location-card.js"

type ReveConfigEntry = ConfigEntry[ReveCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled dashboard card and load it in the frontend."""
    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/reve_static", str(www), cache_headers=False)]
    )
    integration = await async_get_integration(hass, DOMAIN)
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ReveConfigEntry) -> bool:
    """Set up Reve from a config entry (the API key "gateway")."""
    api = ReveApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = ReveCoordinator(hass, entry, api)
    await coordinator.async_load_watches()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_shutdown_watches)

    # Adding / removing chargers (or changing options) reloads the entry. Debounce it:
    # a reload re-polls every charger and the API quota is tight.
    cancel_reload: CALLBACK_TYPE | None = None

    @callback
    def _cancel() -> None:
        nonlocal cancel_reload
        if cancel_reload:
            cancel_reload()
            cancel_reload = None

    async def _async_update_listener(hass: HomeAssistant, entry: ReveConfigEntry) -> None:
        nonlocal cancel_reload
        _cancel()

        @callback
        def _reload(_now: datetime) -> None:
            hass.config_entries.async_schedule_reload(entry.entry_id)

        cancel_reload = async_call_later(hass, RELOAD_DELAY, _reload)

    entry.async_on_unload(_cancel)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    register_charger_devices(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


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
