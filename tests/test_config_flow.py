"""Tests for Pawsync Config Flow."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.pawsync.const import (
    CONF_HOST,
    CONF_ONBOARDING_MODE,
    CONF_SELECTED_FEEDER,
    DOMAIN,
    FLASH_METHOD_OTA,
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
async def test_cloud_onboarding_ota_progress_flow():
    """Test OTA progress step with wait and auto-completion."""
    from custom_components.pawsync.const import FLASH_METHOD_OTA

    flow = PawsyncConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config.config_dir = "/tmp"
    flow.hass.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))

    flow._selected_feeder_cid = "cid_cat_001"
    flow._selected_feeder_info = {
        "cid": "cid_cat_001",
        "mac": "11:22:33:44:55:66",
        "name": "Fluffy's Feeder",
        "model": "PPF-R361S",
        "ip": "192.168.1.99",
    }
    flow._wifi_ssid = "HomeNetwork"
    flow._wifi_password = "Password123"

    with patch.object(flow, "_async_convert_feeder_task", new=AsyncMock(return_value=None)):
        # Step: Flash wizard with OTA
        res = await flow.async_step_flash_wizard({
            "flash_method": FLASH_METHOD_OTA,
        })
        assert res["type"] == "progress"
        assert res["step_id"] == "ota_progress"
        assert res["progress_action"] == "converting"

        # Advance progress step once task is done
        await flow._ota_task
        res_done = await flow.async_step_ota_progress()
        assert res_done["type"] == "progress_done"
        assert res_done["next_step_id"] == "ota_finish"

        # Finish step creates entry
        res_entry = await flow.async_step_ota_finish()
        assert res_entry["type"] == "create_entry"
        assert "Fluffy's Feeder" in res_entry["title"]


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


@pytest.mark.asyncio
async def test_multi_feeder_unique_credentials_isolation():
    """Verify multiple feeders receive unique, decoupled Noise PSK and OTA passwords (AC-7, AC-8)."""
    # Feeder 1
    flow1 = PawsyncConfigFlow()
    flow1.hass = MagicMock()
    flow1.hass.config.config_dir = "/tmp"
    flow1._selected_feeder_cid = "cid_001"
    flow1._selected_feeder_info = {
        "cid": "cid_001",
        "mac": "11:22:33:44:55:01",
        "name": "Feeder 1",
    }
    flow1._wifi_ssid = "HomeWiFi"
    flow1._wifi_password = "Password1"

    res1 = await flow1.async_step_flash_wizard({"flash_method": FLASH_METHOD_SKIP})
    psk1 = res1["data"]["noise_psk"]
    ota1 = res1["data"]["ota_password"]

    # Feeder 2
    flow2 = PawsyncConfigFlow()
    flow2.hass = MagicMock()
    flow2.hass.config.config_dir = "/tmp"
    flow2._selected_feeder_cid = "cid_002"
    flow2._selected_feeder_info = {
        "cid": "cid_002",
        "mac": "11:22:33:44:55:02",
        "name": "Feeder 2",
    }
    flow2._wifi_ssid = "HomeWiFi"
    flow2._wifi_password = "Password1"

    res2 = await flow2.async_step_flash_wizard({"flash_method": FLASH_METHOD_SKIP})
    psk2 = res2["data"]["noise_psk"]
    ota2 = res2["data"]["ota_password"]

    # Ensure keys are strictly decoupled and never collide
    assert psk1 != psk2
    assert ota1 != ota2
    assert len(psk1) == 44
    assert len(psk2) == 44
    assert len(ota1) == 16
    assert len(ota2) == 16


@pytest.mark.asyncio
async def test_cloud_onboarding_recovery_redirect_and_retry():
    """Verify failed adoption redirects to recovery step, and retry adopts feeder."""
    flow = PawsyncConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config.config_dir = "/tmp"
    flow.hass.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))

    flow._selected_feeder_cid = "cid_cat_002"
    flow._selected_feeder_info = {
        "cid": "cid_cat_002",
        "mac": "11:22:33:44:55:66",
        "name": "Luna's Feeder",
        "model": "PPF-R361S",
        "ip": "192.168.1.102",
        "noise_psk": "DUMMY_ORIGINAL_NOISE_PSK_KEY_44B___________=",
    }
    flow._wifi_ssid = "HomeNetwork"
    flow._wifi_password = "Password123"

    with patch.object(flow, "_async_convert_feeder_task", new=AsyncMock(return_value=None)):
        await flow.async_step_flash_wizard({"flash_method": FLASH_METHOD_OTA})
        await flow._ota_task

        # Simulate adoption failure
        flow._adoption_successful = False
        res_done = await flow.async_step_ota_progress()
        assert res_done["type"] == "progress_done"
        assert res_done["next_step_id"] == "recovery"

        # View recovery form
        form = await flow.async_step_recovery()
        assert form["type"] == "form"
        assert form["step_id"] == "recovery"
        assert form["description_placeholders"]["fallback_ssid"] == "Pawsync-Feeder-Fallback"
        assert form["description_placeholders"]["fallback_password"] == "pawsync1234"

        # Action: Retry with adoption success
        with patch("custom_components.pawsync.config_flow.async_auto_adopt_esphome", new=AsyncMock(return_value=True)):
            res_entry = await flow.async_step_recovery({"recovery_action": "retry"})
            assert res_entry["type"] == "create_entry"
            assert "Luna's Feeder" in res_entry["title"]
            # Preserves original Noise PSK
            assert res_entry["data"]["noise_psk"] == "DUMMY_ORIGINAL_NOISE_PSK_KEY_44B___________="


@pytest.mark.asyncio
async def test_cloud_onboarding_recovery_manual_ip():
    """Verify manual IP input in recovery step adopts feeder and updates IP."""
    flow = PawsyncConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config.config_dir = "/tmp"

    flow._selected_feeder_cid = "cid_cat_003"
    flow._selected_feeder_info = {
        "cid": "cid_cat_003",
        "mac": "11:22:33:44:55:77",
        "name": "Milo's Feeder",
        "model": "PPF-R361S",
        "ip": "192.168.1.50",
    }
    flow._wifi_ssid = "HomeNetwork"
    flow._wifi_password = "Password123"

    # 1. Manual IP with connection failure
    with patch("custom_components.pawsync.config_flow.async_auto_adopt_esphome", new=AsyncMock(return_value=False)):
        res_fail = await flow.async_step_recovery({
            "recovery_action": "manual_ip",
            "host": "192.168.10.200",
        })
        assert res_fail["type"] == "form"
        assert res_fail["errors"]["base"] == "cannot_connect_manual_ip"

    # 2. Manual IP with connection success
    with patch("custom_components.pawsync.config_flow.async_auto_adopt_esphome", new=AsyncMock(return_value=True)):
        res_ok = await flow.async_step_recovery({
            "recovery_action": "manual_ip",
            "host": "192.168.10.200",
        })
        assert res_ok["type"] == "create_entry"
        assert res_ok["data"]["host"] == "192.168.10.200"


@pytest.mark.asyncio
async def test_cloud_onboarding_recovery_finish_anyway():
    """Verify proceed without waiting creates config entry directly."""
    flow = PawsyncConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config.config_dir = "/tmp"

    flow._selected_feeder_cid = "cid_cat_004"
    flow._selected_feeder_info = {
        "cid": "cid_cat_004",
        "mac": "11:22:33:44:55:88",
        "name": "Oliver's Feeder",
        "model": "PPF-R361S",
        "ip": "192.168.1.60",
    }
    flow._wifi_ssid = "HomeNetwork"
    flow._wifi_password = "Password123"

    res = await flow.async_step_recovery({"recovery_action": "finish_anyway"})
    assert res["type"] == "create_entry"
    assert "Oliver's Feeder" in res["title"]

