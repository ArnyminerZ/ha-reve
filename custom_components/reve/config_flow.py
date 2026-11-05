"""Config flow: the API key is the gateway, each charger is a subentry."""

from __future__ import annotations

import asyncio
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
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
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


LOCATION_PAGE_SIZE = 100
LOCATION_BATCH = 4  # pages fetched concurrently while searching


def _location_evses(location: dict[str, Any]) -> list[dict[str, Any]]:
    evses = location.get("evses") or []
    return [evses] if isinstance(evses, dict) else evses


async def _find_location(api: ReveApi, evse_id: str) -> dict[str, Any] | None:
    """Scan the CPO's locations until one contains the EVSE.

    The API cannot look a location up by EVSE id, so the CPO (the second part of
    the id, ES*IBD*...) is paged through a few pages at a time and the search
    stops as soon as the EVSE is found.
    """
    party_id = evse_id.split("*")[1]
    page = 1
    while True:
        pages = await asyncio.gather(
            *(
                api.get_locations(party_id, p, LOCATION_PAGE_SIZE)
                for p in range(page, page + LOCATION_BATCH)
            )
        )
        for locations in pages:
            for location in locations:
                if any(e.get("evse_id") == evse_id for e in _location_evses(location)):
                    return location
        if any(len(locations) < LOCATION_PAGE_SIZE for locations in pages):
            return None  # reached the last page
        page += LOCATION_BATCH


class ChargerSubentryFlow(ConfigSubentryFlow):
    """Add a charger, together with every outlet of its location."""

    def __init__(self) -> None:
        super().__init__()
        self._evse_id = ""
        self._name = ""
        self._evse: dict[str, Any] = {}
        self._task: asyncio.Task[dict[str, Any] | None] | None = None
        self._location: dict[str, Any] | None = None

    def _api(self) -> ReveApi:
        return ReveApi(async_get_clientsession(self.hass), self._get_entry().data[CONF_API_KEY])

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            evse_id = user_input[CONF_EVSE_ID].strip().upper()
            if not EVSE_ID_RE.match(evse_id):
                errors[CONF_EVSE_ID] = "invalid_evse_id"
            else:
                try:
                    self._evse = await self._api().get_evse(evse_id)
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
                    self._evse_id = evse_id
                    self._name = (user_input.get("name") or "").strip()
                    return await self.async_step_search()
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

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Find the location of the charger (can take a while: shows progress)."""
        if self._task is None:
            self._task = self.hass.async_create_task(_find_location(self._api(), self._evse_id))
        if not self._task.done():
            return self.async_show_progress(
                step_id="search",
                progress_action="search",
                progress_task=self._task,
                description_placeholders={"evse_id": self._evse_id},
            )
        try:
            self._location = self._task.result()
        except ReveAuthError:
            return self.async_show_progress_done(next_step_id="auth_failed")
        except ReveRateLimitError:
            return self.async_show_progress_done(next_step_id="rate_limited")
        except ReveError as err:
            _LOGGER.warning("Could not look up the location of %s: %s", self._evse_id, err)
            self._location = None
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_auth_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return self.async_abort(reason="invalid_auth")

    async def async_step_rate_limited(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return self.async_abort(reason="rate_limited")

    @callback
    def async_remove(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        location = self._location
        # Without a location we can only add the charger that was entered.
        evses = _location_evses(location) if location else [self._evse]
        found = {
            e["evse_id"]: e for e in evses if e.get("evse_id") and e.get("connectors") is not None
        }
        found.setdefault(self._evse_id, self._evse)
        ordered = sorted(found.items(), key=lambda kv: kv[0])
        known = {s.unique_id for s in entry.subentries.values()}
        new = [(k, v) for k, v in ordered if k not in known]
        if not new:
            return self.async_abort(reason="already_configured")

        base = self._name or (location or {}).get("name") or ""
        multiple = len(ordered) > 1

        def title(eid: str) -> str:
            if not base:
                return eid
            if not multiple:
                return base
            return f"{base} {ordered_ids.index(eid) + 1}"

        ordered_ids = [k for k, _ in ordered]

        def data(eid: str, evse: dict[str, Any]) -> dict[str, Any]:
            result = _charger_data(eid, evse)
            if location:
                result[CONF_LOCATION_ID] = location.get("id")
                result[CONF_LOCATION_NAME] = location.get("name")
            return result

        # The flow itself creates the first one; add the rest directly.
        for eid, evse in new[1:]:
            self.hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType(data(eid, evse)),
                    subentry_type=SUBENTRY_TYPE_CHARGER,
                    title=title(eid),
                    unique_id=eid,
                ),
            )
        eid, evse = new[0]
        return self.async_create_entry(title=title(eid), unique_id=eid, data=data(eid, evse))


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
