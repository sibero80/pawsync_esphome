"""Tests for Pawsync Config Flow."""

import asyncio
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


@pytest.fixture(autouse=True)
def mock_auto_adopt():
    """Mock background esphome auto-adoption task to avoid unawaited coroutines."""
    with patch("custom_components.pawsync.config_flow.async_auto_adopt_esphome", new=MagicMock(return_value=None)):
        yield


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
    res5 = await flow.async_step_flash_wizard({
        "flash_method": FLASH_METHOD_SKIP,
    })
    assert res5["type"] == "create_entry"
    assert "Fluffy's Feeder" in res5["title"]
    assert res5["data"][CONF_SELECTED_FEEDER] == "cid_cat_001"
    assert res5["data"].get("token") is None
    assert "noise_psk" in res5["description_placeholders"]
    assert len(res5["description_placeholders"]["noise_psk"]) == 44


@pytest.mark.asyncio
async def test_options_flow():
    """Test options flow initialization and update."""
    from custom_components.pawsync.config_flow import PawsyncOptionsFlowHandler
    from custom_components.pawsync.const import CONF_UNIT_SYSTEM, UNIT_SYSTEM_IMPERIAL, UNIT_SYSTEM_METRIC

    mock_entry = MagicMock()
    mock_entry.data = {
        CONF_UNIT_SYSTEM: UNIT_SYSTEM_METRIC,
        CONF_HOST: "192.168.1.50",
    }
    mock_entry.options = {}

    options_flow = PawsyncOptionsFlowHandler(mock_entry)
    options_flow.hass = MagicMock()
    options_flow.hass.config.units.is_metric = True

    # 1. Show form
    form = await options_flow.async_step_init()
    assert form["type"] == "form"
    assert form["step_id"] == "init"

    # 2. Submit changes
    res = await options_flow.async_step_init({
        CONF_UNIT_SYSTEM: UNIT_SYSTEM_IMPERIAL,
        CONF_HOST: "192.168.1.99",
        "stager_port": 8100,
    })
    assert res["type"] == "create_entry"
    assert res["data"][CONF_UNIT_SYSTEM] == UNIT_SYSTEM_IMPERIAL
    assert res["data"][CONF_HOST] == "192.168.1.99"
    assert res["data"]["stager_port"] == 8100


@pytest.mark.asyncio
async def test_prerequisites_manual_ip_input():
    """Test entering a manual IP override during prerequisites."""
    from custom_components.pawsync.const import CONF_SSID, CONF_WIFI_PASSWORD

    flow = PawsyncConfigFlow()
    flow.hass = MagicMock()
    flow._selected_feeder_info = {"name": "Test Feeder", "mac": "11:22:33:44:55:66"}

    res = await flow.async_step_prerequisites({
        CONF_SSID: "TestWiFi",
        CONF_WIFI_PASSWORD: "Password123",
        CONF_HOST: "192.168.1.77",
    })
    assert res["type"] == "form"
    assert res["step_id"] == "flash_wizard"
    assert flow._selected_feeder_info["ip"] == "192.168.1.77"
