"""Tests for the Reve integration."""

from datetime import timedelta

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.reve.api import ReveStatus
from custom_components.reve.const import DOMAIN

from .conftest import EVSE

EVSE_ID = "ES*IBD*E142206*1"


def make_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Reve",
        unique_id="k",
        data={"api_key": "secret", "rate_tier": "standard"},
        subentries_data=[
            ConfigSubentryData(
                data={
                    "evse_id": EVSE_ID,
                    "connectors": EVSE["connectors"],
                    "coordinates": EVSE["coordinates"],
                    "physical_reference": "1",
                },
                subentry_type="charger",
                title="Garage",
                unique_id=EVSE_ID,
            )
        ],
    )


async def test_setup_devices_and_entities(hass: HomeAssistant, mock_api) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.garage")
    assert state is not None and state.state == "charging"
    assert hass.states.get("binary_sensor.garage_free").state == "off"

    reg = dr.async_get(hass)
    parent = reg.async_get_device_by_identifier((DOMAIN, EVSE_ID), entry.entry_id)
    child = reg.async_get_child_device_by_identifier((DOMAIN, f"{EVSE_ID}_conn_1"), entry.entry_id)
    assert parent and child
    assert child.parent_device_id == parent.id
    assert child.name == "Connector 1"
    ents = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert any(e.unique_id.endswith("max_power") for e in ents)


async def test_watch_notifies_when_free(hass: HomeAssistant, mock_api) -> None:
    from pytest_homeassistant_custom_component.common import async_mock_service

    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    calls = async_mock_service(hass, "notify", "send_message")
    events = []
    hass.bus.async_listen("reve_charger_available", events.append)

    await hass.services.async_call(
        DOMAIN,
        "watch_availability",
        {
            "entity_id": "sensor.garage",
            "duration": {"hours": 1},
            "notify_entity_id": ["notify.phone"],
        },
        blocking=True,
    )
    assert hass.states.get("sensor.garage_availability_alert_until").state != "unknown"

    mock_api.get_status.return_value = ReveStatus("AVAILABLE", dt_util.utcnow())
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=21))
    await hass.async_block_till_done()

    assert len(calls) == 1 and calls[0].data["entity_id"] == ["notify.phone"]
    assert len(events) == 1
    assert hass.states.get("sensor.garage_availability_alert_until").state == "unknown"
    assert hass.states.get("event.garage_availability_alert").state != "unknown"
