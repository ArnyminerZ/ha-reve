"""Sensors: charger status + per-connector (child device) specs."""

from __future__ import annotations

from datetime import datetime, timedelta

import voluptuous as vol
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EntityCategory, UnitOfElectricCurrent, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import ChildDeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import ReveConfigEntry
from .const import (
    ATTR_DURATION,
    ATTR_MESSAGE,
    ATTR_NOTIFY_ENTITIES,
    CONF_CONNECTORS,
    DOMAIN,
    SERVICE_CANCEL_WATCH,
    SERVICE_WATCH,
    STATUS_AVAILABLE,
    STATUS_OPTIONS,
)
from .coordinator import ReveCoordinator, Watch
from .entity import ReveChargerEntity, charger_subentries

PARALLEL_UPDATES = 0
MAX_WATCH = timedelta(days=7)

WATCH_SCHEMA = {
    vol.Required(ATTR_DURATION, default=timedelta(hours=2)): cv.time_period,
    vol.Optional(ATTR_NOTIFY_ENTITIES, default=[]): cv.entity_ids,
    vol.Optional(ATTR_MESSAGE): cv.string,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ReveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    registry = dr.async_get(hass)

    for sub in charger_subentries(entry):
        evse_id = sub.data["evse_id"]
        async_add_entities(
            [
                ReveStatusSensor(coordinator, sub),
                ReveLastChangeSensor(coordinator, sub),
                ReveWatchSensor(coordinator, sub),
            ],
            config_subentry_id=sub.subentry_id,
        )
        parent = registry.async_get_device_by_identifier((DOMAIN, evse_id), entry.entry_id)
        if parent is None:
            continue
        connector_entities: list[SensorEntity] = []
        for number, conn in enumerate(sub.data.get(CONF_CONNECTORS) or [], start=1):
            connector_entities += [
                ReveConnectorPower(coordinator, evse_id, parent.id, number, conn),
                ReveConnectorCurrent(coordinator, evse_id, parent.id, number, conn),
                ReveConnectorType(coordinator, evse_id, parent.id, number, conn),
            ]
        async_add_entities(connector_entities, config_subentry_id=sub.subentry_id)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_WATCH, WATCH_SCHEMA, "async_watch_availability")
    platform.async_register_entity_service(SERVICE_CANCEL_WATCH, None, "async_cancel_watch")


class ReveStatusSensor(ReveChargerEntity, SensorEntity):
    """Main entity of the charger: its live status."""

    _attr_name = None
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_OPTIONS
    _attr_translation_key = "status"

    def __init__(self, coordinator: ReveCoordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator, subentry)
        self._attr_unique_id = f"{self.evse_id}_status"

    @property
    def native_value(self) -> str | None:
        return self.status.status.lower() if self.status else None

    async def async_watch_availability(
        self,
        duration: timedelta,
        notify_entity_id: list[str],
        message: str | None = None,
    ) -> None:
        """Notify when this charger becomes available within `duration`."""
        if duration <= timedelta(0) or duration > MAX_WATCH:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_duration"
            )
        if self.status and self.status.status == STATUS_AVAILABLE:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="already_available",
                translation_placeholders={
                    "name": self.device_entry.name_by_user or self.device_entry.name
                    if self.device_entry
                    else self.evse_id
                },
            )
        self.coordinator.start_watch(
            self.evse_id,
            Watch(dt_util.utcnow() + duration, notify_entity_id, message),
        )

    async def async_cancel_watch(self) -> None:
        self.coordinator.cancel_watch(self.evse_id)


class ReveLastChangeSensor(ReveChargerEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_status_change"

    def __init__(self, coordinator: ReveCoordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator, subentry)
        self._attr_unique_id = f"{self.evse_id}_last_status_change"

    @property
    def native_value(self) -> datetime | None:
        return self.status.last_updated if self.status else None


class ReveWatchSensor(ReveChargerEntity, SensorEntity):
    """Shows until when an availability alert is armed."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "watching_until"

    def __init__(self, coordinator: ReveCoordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator, subentry)
        self._attr_unique_id = f"{self.evse_id}_watching_until"

    @property
    def native_value(self) -> datetime | None:
        watch = self.coordinator.watches.get(self.evse_id)
        return watch.expires_at if watch else None


class ReveConnectorEntity(CoordinatorEntity[ReveCoordinator], SensorEntity):
    """Entity of a connector child device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: ReveCoordinator,
        evse_id: str,
        parent_id: str,
        number: int,
        conn: dict,
    ) -> None:
        super().__init__(coordinator)
        self.evse_id = evse_id
        self._conn = conn
        self._number = number
        self._attr_device_info = ChildDeviceInfo(
            identifiers={(DOMAIN, f"{evse_id}_conn_{number}")},
            parent_device_id=parent_id,
            translation_key="connector",
            translation_placeholders={"number": str(number)},
        )


class ReveConnectorPower(ReveConnectorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_translation_key = "connector_max_power"

    def __init__(self, coordinator, evse_id, parent_id, number, conn) -> None:
        super().__init__(coordinator, evse_id, parent_id, number, conn)
        self._attr_unique_id = f"{evse_id}_conn_{number}_max_power"
        self._attr_native_value = conn.get("max_electric_power")


class ReveConnectorCurrent(ReveConnectorEntity):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_translation_key = "connector_max_current"

    def __init__(self, coordinator, evse_id, parent_id, number, conn) -> None:
        super().__init__(coordinator, evse_id, parent_id, number, conn)
        self._attr_unique_id = f"{evse_id}_conn_{number}_max_current"
        self._attr_native_value = conn.get("max_amperage")


class ReveConnectorType(ReveConnectorEntity):
    _attr_translation_key = "connector_type"

    def __init__(self, coordinator, evse_id, parent_id, number, conn) -> None:
        super().__init__(coordinator, evse_id, parent_id, number, conn)
        self._attr_unique_id = f"{evse_id}_conn_{number}_type"
        self._attr_native_value = conn.get("standard")
        self._attr_extra_state_attributes = {
            k: conn.get(k) for k in ("format", "power_type", "max_voltage")
        }
