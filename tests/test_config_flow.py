"""Config flow tests."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.reve.api import ReveAuthError, ReveNotFoundError
from custom_components.reve.const import DOMAIN


async def test_user_flow_and_add_charger(hass: HomeAssistant, mock_api) -> None:
    entry, done = await _start_charger_flow(hass, mock_api, "es*ibd*e142206*1", "Garage")
    assert done["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.title == "Garage"
    assert subentry.data["evse_id"] == "ES*IBD*E142206*1"
    assert subentry.data["connectors"][0]["max_amperage"] == 32


async def test_bad_key(hass: HomeAssistant, mock_api) -> None:
    mock_api.validate.side_effect = ReveAuthError
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "x", "rate_tier": "standard"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_unknown_evse(hass: HomeAssistant, mock_api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "k", "rate_tier": "standard"}
    )
    entry = result["result"]
    mock_api.get_evse.side_effect = ReveNotFoundError
    sub = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "charger"), context={"source": "user"}
    )
    res = await hass.config_entries.subentries.async_configure(
        sub["flow_id"], {"evse_id": "ES*IBD*E1*1"}
    )
    assert res["errors"] == {"evse_id": "evse_not_found"}


async def _start_charger_flow(hass, mock_api, evse_id, name=None):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "k", "rate_tier": "standard"}
    )
    entry = result["result"]
    sub = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "charger"), context={"source": "user"}
    )
    data = {"evse_id": evse_id}
    if name:
        data["name"] = name
    res = await hass.config_entries.subentries.async_configure(sub["flow_id"], data)
    while res["type"] is FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done()
        res = await hass.config_entries.subentries.async_configure(sub["flow_id"])
    return entry, res


async def test_adding_one_outlet_adds_the_whole_location(hass: HomeAssistant, mock_api) -> None:
    entry, done = await _start_charger_flow(hass, mock_api, "ES*IBD*E87442*1", "Office")
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    # Outlets of the location have different station numbers (E87441 / E87442).
    subs = {s.unique_id: s for s in entry.subentries.values()}
    assert {k: s.title for k, s in subs.items()} == {
        "ES*IBD*E87441*1": "Office 1",
        "ES*IBD*E87442*1": "Office 2",
        "ES*IBD*E87442*2": "Office 3",
    }
    assert subs["ES*IBD*E87441*1"].data["location_name"] == "NA-Oteiza-001"


async def test_not_in_any_location_adds_only_that_charger(hass: HomeAssistant, mock_api) -> None:
    mock_api.locations = []
    entry, done = await _start_charger_flow(hass, mock_api, "ES*IBD*E142206*1")
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert [s.unique_id for s in entry.subentries.values()] == ["ES*IBD*E142206*1"]


async def test_invalid_evse_id(hass: HomeAssistant, mock_api) -> None:
    _, bad = await _start_charger_flow(hass, mock_api, "nope")
    assert bad["errors"] == {"evse_id": "invalid_evse_id"}
