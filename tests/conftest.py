"""Test fixtures."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.reve.api import ReveNotFoundError, ReveStatus


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


EVSE = {
    "id": "abc",
    "evse_id": "ES*IBD*E142206*1",
    "physical_reference": "1",
    "coordinates": {"latitude": "39.1", "longitude": "-0.4"},
    "connectors": [
        {
            "id": "c1",
            "standard": "IEC_62196_T2",
            "format": "SOCKET",
            "power_type": "AC_3_PHASE",
            "max_electric_power": 22000,
            "max_voltage": 230,
            "max_amperage": 32,
        },
    ],
}


@pytest.fixture
def mock_api():
    status = ReveStatus("CHARGING", dt_util.utcnow())
    with (
        patch("custom_components.reve.ReveApi", autospec=True) as cls,
        patch("custom_components.reve.config_flow.ReveApi", new=cls),
    ):
        api = cls.return_value
        api.validate = AsyncMock()

        async def get_evse(evse_id):
            if evse_id in api.stations:
                return {**EVSE, "evse_id": evse_id}
            raise ReveNotFoundError

        api.stations = {"ES*IBD*E142206*1", "ES*IBD*E11900*1", "ES*IBD*E11900*2"}
        api.get_evse = AsyncMock(side_effect=get_evse)
        api.get_status = AsyncMock(return_value=status)
        yield api
