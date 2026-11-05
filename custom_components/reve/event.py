"""Event entity fired when a watched charger becomes available."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ReveConfigEntry
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
            [ReveAvailableEvent(entry.runtime_data, sub)],
            config_subentry_id=sub.subentry_id,
        )


class ReveAvailableEvent(ReveChargerEntity, EventEntity):
    _attr_translation_key = "availability_alert"
    _attr_event_types = ["available"]

    def __init__(self, coordinator: ReveCoordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator, subentry)
        self._attr_unique_id = f"{self.evse_id}_availability_alert"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_available_listener(self._on_available))

    @callback
    def _on_available(self, evse_id: str, message: str | None) -> None:
        if evse_id == self.evse_id:
            self._trigger_event("available", {"message": message})
            self.async_write_ha_state()
