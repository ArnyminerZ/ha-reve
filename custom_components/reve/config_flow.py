"""Config flow: the API key is the gateway, each charger is a subentry."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    ReveApi,
    ReveAuthError,
    ReveConnectionError,
    ReveError,
    ReveNotFoundError,
    ReveRateLimitError,
)
from .const import (
    CONF_API_KEY,
    CONF_CONNECTORS,
    CONF_COORDINATES,
    CONF_EVSE_ID,
    CONF_EVSE_UID,
    CONF_PHYSICAL_REFERENCE,
    CONF_RATE_TIER,
    CONF_SCAN_INTERVAL,
    DEFAULT_INTERVAL_MINUTES,
    DOMAIN,
    MAX_INTERVAL_MINUTES,
    SUBENTRY_TYPE_CHARGER,
    TIER_SPECIAL,
    TIER_STANDARD,
    min_interval_minutes,
)

_LOGGER = logging.getLogger(__name__)
MAX_SIBLINGS = 12
EVSE_ID_RE = re.compile(r"^[A-Z]{2}\*[A-Z0-9]{3}\*E[A-Z0-9*]+$")

TIER_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[TIER_STANDARD, TIER_SPECIAL],
        translation_key="rate_tier",
        mode=SelectSelectorMode.DROPDOWN,
    )
)


async def _validate_key(hass, api_key: str) -> str | None:
    """Return an error key, or None when the key works."""
    try:
        await ReveApi(async_get_clientsession(hass), api_key).validate()
    except ReveAuthError:
        return "invalid_auth"
    except ReveRateLimitError:
        return "rate_limited"
    except ReveConnectionError:
        return "cannot_connect"
    except ReveError:
        return "unknown"
    return None


def _key_id(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


class ReveConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the hub (API key) flow."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_CHARGER: ChargerSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ReveOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            await self.async_set_unique_id(_key_id(key))
            self._abort_if_unique_id_configured()
            if error := await _validate_key(self.hass, key):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="Reve",
                    data={
                        CONF_API_KEY: key,
                        CONF_RATE_TIER: user_input[CONF_RATE_TIER],
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_RATE_TIER, default=TIER_STANDARD): TIER_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            if error := await _validate_key(self.hass, key):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    unique_id=_key_id(key),
                    data_updates={CONF_API_KEY: key},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            if error := await _validate_key(self.hass, key):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=_key_id(key),
                    data_updates={
                        CONF_API_KEY: key,
                        CONF_RATE_TIER: user_input[CONF_RATE_TIER],
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(
                        CONF_RATE_TIER,
                        default=entry.data.get(CONF_RATE_TIER, TIER_STANDARD),
                    ): TIER_SELECTOR,
                }
            ),
            errors=errors,
        )


def _charger_data(evse_id: str, evse: dict[str, Any]) -> dict[str, Any]:
    """Static data stored in a charger subentry."""
    coords = evse.get("coordinates") or {}
    return {
        CONF_EVSE_ID: evse_id,
        CONF_EVSE_UID: evse.get("id"),
        CONF_PHYSICAL_REFERENCE: evse.get("physical_reference"),
        CONF_COORDINATES: {
            "latitude": coords.get("latitude"),
            "longitude": coords.get("longitude"),
        },
        CONF_CONNECTORS: [
            {
                "id": c.get("id"),
                "standard": c.get("standard"),
                "format": c.get("format"),
                "power_type": c.get("power_type"),
                "max_electric_power": c.get("max_electric_power"),
                "max_voltage": c.get("max_voltage"),
                "max_amperage": c.get("max_amperage"),
            }
            for c in evse.get("connectors") or []
        ],
    }


async def _discover_station(api: ReveApi, evse_id: str) -> dict[str, dict[str, Any]]:
    """Fetch the entered EVSE plus its siblings (same station, other numbers).

    EVSE ids end in the outlet number (ES*IBD*E11900*1, ...*2, ...). Siblings
    are probed from 1 upwards; probing stops at the first gap after the entered
    number. Only the entered EVSE is allowed to raise; sibling failures are skipped.
    """
    found = {evse_id: await api.get_evse(evse_id)}
    prefix, _, number = evse_id.rpartition("*")
    if not number.isdigit():
        return found
    entered = int(number)
    for n in range(1, MAX_SIBLINGS + 1):
        sibling = f"{prefix}*{n}"
        if sibling == evse_id:
            continue
        try:
            found[sibling] = await api.get_evse(sibling)
        except ReveAuthError:
            raise
        except ReveNotFoundError:
            if n > entered:
                break
        except ReveError:
            _LOGGER.debug("Could not probe sibling %s", sibling)
    return dict(sorted(found.items(), key=lambda kv: int(kv[0].rpartition("*")[2])))


class ChargerSubentryFlow(ConfigSubentryFlow):
    """Add a charger (and the other outlets of its station) by EVSE id."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            evse_id = user_input[CONF_EVSE_ID].strip().upper()
            if not EVSE_ID_RE.match(evse_id):
                errors[CONF_EVSE_ID] = "invalid_evse_id"
            else:
                api = ReveApi(async_get_clientsession(self.hass), entry.data[CONF_API_KEY])
                try:
                    found = await _discover_station(api, evse_id)
                except ReveNotFoundError:
                    errors[CONF_EVSE_ID] = "evse_not_found"
                except ReveAuthError:
                    errors["base"] = "invalid_auth"
                except ReveRateLimitError:
                    errors["base"] = "rate_limited"
                except ReveConnectionError:
                    errors["base"] = "cannot_connect"
                except ReveError:
                    errors["base"] = "unknown"
                else:
                    known = {s.unique_id for s in entry.subentries.values()}
                    new = {k: v for k, v in found.items() if k not in known}
                    if not new:
                        return self.async_abort(reason="already_configured")
                    name = (user_input.get("name") or "").strip()
                    multiple = len(found) > 1

                    def title(eid: str) -> str:
                        if not name:
                            return eid
                        return f"{name} {eid.rpartition('*')[2]}" if multiple else name

                    items = list(new.items())
                    # The flow itself creates the first one; add the rest directly.
                    for eid, evse in items[1:]:
                        self.hass.config_entries.async_add_subentry(
                            entry,
                            ConfigSubentry(
                                data=MappingProxyType(_charger_data(eid, evse)),
                                subentry_type=SUBENTRY_TYPE_CHARGER,
                                title=title(eid),
                                unique_id=eid,
                            ),
                        )
                    eid, evse = items[0]
                    return self.async_create_entry(
                        title=title(eid), unique_id=eid, data=_charger_data(eid, evse)
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EVSE_ID): str,
                    vol.Optional("name"): str,
                }
            ),
            errors=errors,
        )


class ReveOptionsFlow(OptionsFlow):
    """Polling interval, bounded by the API quota."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        tier = entry.data.get(CONF_RATE_TIER, TIER_STANDARD)
        chargers = sum(
            1 for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_CHARGER
        )
        minimum = min_interval_minutes(tier, chargers)
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        current = max(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_INTERVAL_MINUTES[tier]),
            minimum,
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=minimum,
                            max=MAX_INTERVAL_MINUTES,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
            description_placeholders={"minimum": str(minimum)},
        )
