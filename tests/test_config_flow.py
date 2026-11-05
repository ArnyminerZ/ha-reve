"""Config flow tests."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.reve.api import ReveAuthError, ReveNotFoundError
from custom_components.reve.const import DOMAIN


async def test_user_flow_and_add_charger(hass: HomeAssistant, mock_api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "secret", "rate_tier": "standard"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await hass.async_block_till_done()

    sub = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "charger"), context={"source": "user"}
    )
    bad = await hass.config_entries.subentries.async_configure(sub["flow_id"], {"evse_id": "nope"})
    assert bad["errors"] == {"evse_id": "invalid_evse_id"}
    done = await hass.config_entries.subentries.async_configure(
        sub["flow_id"], {"evse_id": "es*ibd*e142206*1", "name": "Garage"}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
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


async def test_adding_one_outlet_adds_the_whole_station(hass: HomeAssistant, mock_api) -> None:
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
    done = await hass.config_entries.subentries.async_configure(
        sub["flow_id"], {"evse_id": "ES*IBD*E11900*1", "name": "Office"}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    subs = {s.unique_id: s.title for s in entry.subentries.values()}
    assert subs == {
        "ES*IBD*E11900*1": "Office 1",
        "ES*IBD*E11900*2": "Office 2",
    }

    # Entering the sibling again finds nothing new.
    sub = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "charger"), context={"source": "user"}
    )
    again = await hass.config_entries.subentries.async_configure(
        sub["flow_id"], {"evse_id": "ES*IBD*E11900*2"}
    )
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "already_configured"
