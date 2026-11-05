"""Binary sensors for a charger."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ReveConfigEntry
from .const import STATUS_AVAILABLE, STATUS_FAULT
from .coordinator import ReveCoordinator
from .entity import ReveChargerEntity, charger_subentries

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ReveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for sub in charger_subentries(entry):
        async_add_entities(
            [
                ReveFreeBinarySensor(entry.runtime_data, sub),
                ReveProblemBinarySensor(entry.runtime_data, sub),
            ],
            config_subentry_id=sub.subentry_id,
        )


class ReveFreeBinarySensor(ReveChargerEntity, BinarySensorEntity):
    """On while the charger is free to use."""

    _attr_translation_key = "free"

    def __init__(self, coordinator: ReveCoordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator, subentry)
        self._attr_unique_id = f"{self.evse_id}_free"

    @property
    def is_on(self) -> bool | None:
        return self.status.status == STATUS_AVAILABLE if self.status else None


class ReveProblemBinarySensor(ReveChargerEntity, BinarySensorEntity):
    """On when the charger is out of order."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: ReveCoordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator, subentry)
        self._attr_unique_id = f"{self.evse_id}_problem"

    @property
    def is_on(self) -> bool | None:
        return self.status.status in STATUS_FAULT if self.status else None
