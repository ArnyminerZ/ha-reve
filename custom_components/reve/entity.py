"""Shared entity helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ReveStatus
from .const import (
    CONF_CONNECTORS,
    CONF_COORDINATES,
    CONF_EVSE_ID,
    CONF_PHYSICAL_REFERENCE,
    DOMAIN,
    SUBENTRY_TYPE_CHARGER,
)
from .coordinator import ReveCoordinator

if TYPE_CHECKING:
    from . import ReveConfigEntry


def charger_subentries(entry: ReveConfigEntry) -> list[ConfigSubentry]:
    return [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_CHARGER]


def register_charger_devices(hass: HomeAssistant, entry: ReveConfigEntry) -> None:
    """Create the parent device of each charger (children need it to exist)."""
    registry = dr.async_get(hass)
    for sub in charger_subentries(entry):
        evse_id = sub.data[CONF_EVSE_ID]
        connectors = sub.data.get(CONF_CONNECTORS) or []
        coords = sub.data.get(CONF_COORDINATES) or {}
        url = None
        if coords.get("latitude") and coords.get("longitude"):
            url = f"https://www.google.com/maps?q={coords['latitude']},{coords['longitude']}"
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=sub.subentry_id,
            identifiers={(DOMAIN, evse_id)},
            manufacturer="Reve",
            model=connectors[0].get("standard") if connectors else None,
            name=sub.title,
            serial_number=sub.data.get(CONF_PHYSICAL_REFERENCE) or evse_id,
            configuration_url=url,
            entry_type=dr.DeviceEntryType.SERVICE,
        )


class ReveChargerEntity(CoordinatorEntity[ReveCoordinator]):
    """Entity belonging to the charger device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ReveCoordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)
        self.evse_id: str = subentry.data[CONF_EVSE_ID]
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self.evse_id)})

    @property
    def status(self) -> ReveStatus | None:
        return (self.coordinator.data or {}).get(self.evse_id)

    @property
    def available(self) -> bool:
        return super().available and self.status is not None
