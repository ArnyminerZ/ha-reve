"""Data coordinator and availability watcher for Reve."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    ReveApi,
    ReveAuthError,
    ReveConnectionError,
    ReveError,
    ReveNotFoundError,
    ReveRateLimitError,
    ReveStatus,
)
from .const import (
    CONF_EVSE_ID,
    CONF_RATE_TIER,
    CONF_SCAN_INTERVAL,
    DEFAULT_INTERVAL_MINUTES,
    DOMAIN,
    EVENT_CHARGER_AVAILABLE,
    STATUS_AVAILABLE,
    STORAGE_VERSION,
    SUBENTRY_TYPE_CHARGER,
    TIER_STANDARD,
    min_interval_minutes,
)

if TYPE_CHECKING:
    from . import ReveConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Watch:
    """A pending "tell me when this charger is free" request."""

    expires_at: datetime
    notify_entities: list[str]
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "expires_at": self.expires_at.isoformat(),
            "notify_entities": self.notify_entities,
            "message": self.message,
        }


class ReveCoordinator(DataUpdateCoordinator[dict[str, ReveStatus]]):
    """Polls the status of every configured charger."""

    config_entry: ReveConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: ReveApi) -> None:
        tier = entry.data.get(CONF_RATE_TIER, TIER_STANDARD)
        chargers = [
            s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_CHARGER
        ]
        minutes = max(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_INTERVAL_MINUTES[tier]),
            min_interval_minutes(tier, len(chargers)),
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.api = api
        self.watches: dict[str, Watch] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.watches"
        )
        self._expiry_timers: dict[str, CALLBACK_TYPE] = {}
        self._available_listeners: list[Callable[[str, str | None], None]] = []

    @property
    def evse_ids(self) -> list[str]:
        return [
            s.data[CONF_EVSE_ID]
            for s in self.config_entry.subentries.values()
            if s.subentry_type == SUBENTRY_TYPE_CHARGER
        ]

    # --- polling -----------------------------------------------------------

    async def _async_update_data(self) -> dict[str, ReveStatus]:
        data: dict[str, ReveStatus] = {}
        errors: list[Exception] = []
        for evse_id in self.evse_ids:
            try:
                data[evse_id] = await self.api.get_status(evse_id)
            except ReveAuthError as err:
                raise ConfigEntryAuthFailed from err
            except ReveNotFoundError:
                _LOGGER.warning("Charger %s was not found by the Reve API", evse_id)
            except (ReveRateLimitError, ReveConnectionError, ReveError) as err:
                _LOGGER.debug("Could not update %s: %s", evse_id, err)
                errors.append(err)
                # Keep the last known value; the quota is tight, don't flap.
                if self.data and evse_id in self.data:
                    data[evse_id] = self.data[evse_id]
        if errors and not data:
            raise UpdateFailed(f"Reve API error: {errors[0]}") from errors[0]
        await self._async_process_watches(data)
        return data

    # --- availability watch ------------------------------------------------

    async def async_load_watches(self) -> None:
        """Restore watches persisted across restarts."""
        stored = await self._store.async_load() or {}
        now = dt_util.utcnow()
        for evse_id, raw in stored.items():
            expires = dt_util.parse_datetime(raw.get("expires_at", ""))
            if evse_id in self.evse_ids and expires and expires > now:
                self._set_watch(
                    evse_id,
                    Watch(expires, raw.get("notify_entities", []), raw.get("message")),
                )

    def _set_watch(self, evse_id: str, watch: Watch) -> None:
        self._clear_timer(evse_id)
        self.watches[evse_id] = watch

        @callback
        def _expire(_now: datetime) -> None:
            self._expiry_timers.pop(evse_id, None)
            self.cancel_watch(evse_id)

        self._expiry_timers[evse_id] = async_track_point_in_utc_time(
            self.hass, _expire, watch.expires_at
        )

    def _clear_timer(self, evse_id: str) -> None:
        if timer := self._expiry_timers.pop(evse_id, None):
            timer()

    def _save(self) -> None:
        self._store.async_delay_save(lambda: {k: w.as_dict() for k, w in self.watches.items()}, 1)

    @callback
    def start_watch(self, evse_id: str, watch: Watch) -> None:
        self._set_watch(evse_id, watch)
        self._save()
        self.async_update_listeners()

    @callback
    def cancel_watch(self, evse_id: str) -> None:
        self._clear_timer(evse_id)
        if self.watches.pop(evse_id, None):
            self._save()
            self.async_update_listeners()

    @callback
    def async_add_available_listener(
        self, listener: Callable[[str, str | None], None]
    ) -> CALLBACK_TYPE:
        """Call listener(evse_id, message) when a watched charger is freed."""
        self._available_listeners.append(listener)
        return lambda: self._available_listeners.remove(listener)

    async def _async_process_watches(self, data: dict[str, ReveStatus]) -> None:
        for evse_id, watch in list(self.watches.items()):
            status = data.get(evse_id)
            if status is None or status.status != STATUS_AVAILABLE:
                continue
            self.cancel_watch(evse_id)
            await self._async_notify(evse_id, watch)

    async def _async_notify(self, evse_id: str, watch: Watch) -> None:
        title = self._charger_title(evse_id)
        message = watch.message or f"{title} is now available."
        self.hass.bus.async_fire(EVENT_CHARGER_AVAILABLE, {"evse_id": evse_id, "name": title})
        for listener in self._available_listeners:
            listener(evse_id, message)
        if watch.notify_entities:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": watch.notify_entities, "title": title, "message": message},
                blocking=False,
            )
        else:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": message,
                    "notification_id": f"{DOMAIN}_{evse_id}",
                },
                blocking=False,
            )

    def _charger_title(self, evse_id: str) -> str:
        for sub in self.config_entry.subentries.values():
            if sub.data.get(CONF_EVSE_ID) == evse_id:
                return sub.title
        return evse_id

    @callback
    def async_shutdown_watches(self) -> None:
        for timer in self._expiry_timers.values():
            timer()
        self._expiry_timers.clear()
