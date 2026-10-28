"""Tests for Pawsync Config Flow."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.pawsync.const import (
    CONF_HOST,
    CONF_ONBOARDING_MODE,
    CONF_SELECTED_FEEDER,
    DOMAIN,
    FLASH_METHOD_SKIP,
    MODE_CLOUD_ONBOARDING,
    MODE_DIRECT_ESPHOME,
)
from custom_components.pawsync.config_flow import PawsyncConfigFlow


@pytest.mark.asyncio
async def test_direct_esphome_flow():
    """Test manual/direct ESPHome IP adoption flow."""
    flow = PawsyncConfigFlow()
    flow.hass = MagicMock()

    # Step 1: User chooses direct esphome
    res1 = await flow.async_step_user({CONF_ONBOARDING_MODE: MODE_DIRECT_ESPHOME})
    assert res1["type"] == "form"
    assert res1["step_id"] == "direct_esphome"

    # Step 2: User provides host
    res2 = await flow.async_step_direct_esphome({
        "name": "Cat Feeder Local",
        CONF_HOST: "192.168.1.45",
    })
    assert res2["type"] == "create_entry"
    assert res2["title"] == "Cat Feeder Local"
    assert res2["data"][CONF_HOST] == "192.168.1.45"


@pytest.mark.asyncio
async def test_cloud_onboarding_full_flow():
    """Test complete guided cloud onboarding flow."""
    flow = PawsyncConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config.config_dir = "/tmp"

    # Step 1: User selects cloud onboarding
    res1 = await flow.async_step_user({CONF_ONBOARDING_MODE: MODE_CLOUD_ONBOARDING})
    assert res1["type"] == "form"
    assert res1["step_id"] == "cloud"

    # Step 2: Cloud login
    flow.hass.config.time_zone = "America/New_York"
    flow.hass.config.country = "US"
    mock_client = AsyncMock()
    mock_client.async_login.return_value = {
        "account_id": "acc_777",
        "token": "tok_888",
        "source": "pawsync",
    }
    mock_client.async_get_devices.return_value = [
        {
            "cid": "cid_cat_001",
            "mac": "11:22:33:44:55:66",
            "name": "Fluffy's Feeder",
            "model": "VS_WB_PFM_PPF-R361S-WUS_US",
            "is_feeder": True,
            "status": "online",
        }
    ]

    with patch("custom_components.pawsync.config_flow.PawsyncApiClient", return_value=mock_client):
        res2 = await flow.async_step_cloud({
            "email": "catlover@example.com",
            "password": "SuperSecretPassword",
            "country_code": "US",
        })

    assert res2["type"] == "form"
    assert res2["step_id"] == "select_feeders"

    # Step 3: Select Feeder
    res3 = await flow.async_step_select_feeders({
        CONF_SELECTED_FEEDER: "cid_cat_001",
    })
    assert res3["type"] == "form"
    assert res3["step_id"] == "prerequisites"

    # Step 4: Prerequisites & Wi-Fi
    res4 = await flow.async_step_prerequisites({
        "wifi_ssid": "HomeNetwork",
        "wifi_password": "Pass",
        "confirm_prerequisites": True,
    })
    assert res4["type"] == "form"
    assert res4["step_id"] == "flash_wizard"

    # Step 5: Flash wizard (choose skip or manual to complete)
    with patch("custom_components.pawsync.config_flow.async_auto_adopt_esphome", new_callable=MagicMock):
        res5 = await flow.async_step_flash_wizard({
            "flash_method": FLASH_METHOD_SKIP,
        })
    assert res5["type"] == "create_entry"
    assert "Fluffy's Feeder" in res5["title"]
    assert res5["data"][CONF_SELECTED_FEEDER] == "cid_cat_001"
    assert "noise_psk" in res5["description_placeholders"]
    assert len(res5["description_placeholders"]["noise_psk"]) == 44
