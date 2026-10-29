"""Tests for post-adoption cloud settings restoration engine."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.pawsync.const import DOMAIN
from custom_components.pawsync.restore_manager import (
    async_restore_cloud_settings,
    convert_repeat_to_days_str,
    find_esphome_service,
    format_timesec_to_hhmm,
)


def test_convert_repeat_to_days_str():
    """Verify bitmask and alias conversion to ESPHome days string."""
    assert convert_repeat_to_days_str(127) == "All"
    assert convert_repeat_to_days_str("all") == "All"
    assert convert_repeat_to_days_str("daily") == "All"
    assert convert_repeat_to_days_str(62) == "Weekdays"
    assert convert_repeat_to_days_str(0x3E) == "Weekdays"
    assert convert_repeat_to_days_str(65) == "Weekends"
    assert convert_repeat_to_days_str(0x41) == "Weekends"

    # Mo (0x02) + We (0x08)
    assert convert_repeat_to_days_str(0x02 | 0x08) == "Mo,We"
    # Mo (0x02) + Fr (0x20) + Su (0x01)
    assert convert_repeat_to_days_str(0x02 | 0x20 | 0x01) == "Mo,Fr,Su"


def test_format_timesec_to_hhmm():
    """Verify seconds past midnight conversion to HH:MM."""
    assert format_timesec_to_hhmm(0) == "00:00"
    assert format_timesec_to_hhmm(28800) == "08:00"
    assert format_timesec_to_hhmm(64800) == "18:00"
    assert format_timesec_to_hhmm(65700) == "18:15"
    assert format_timesec_to_hhmm(None) == "08:00"


@pytest.mark.asyncio
async def test_restore_cloud_settings_no_backup():
    """Verify graceful handling when no backup exists."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    entry = MagicMock()
    entry.data = {"feeder_info": {"mac": "11:22:33:44:55:66"}}

    with patch("custom_components.pawsync.restore_manager.load_cloud_backup", return_value=None):
        success = await async_restore_cloud_settings(hass, entry)
        assert success is False


@pytest.mark.asyncio
async def test_restore_cloud_settings_success():
    """Verify full replay of density, switches, surplus, and meal schedule into ESPHome."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    called_services = []

    async def mock_async_call(domain, service, data=None, blocking=True):
        called_services.append((domain, service, data))
        return True

    hass.services.async_call = mock_async_call
    hass.services.async_services.return_value = {
        "esphome": {
            "pawsync_feeder_set_meal_schedule": MagicMock(),
        }
    }
    hass.states.async_entity_ids.side_effect = lambda domain: {
        "number": [
            "number.pawsync_feeder_grams_per_portion_kibble_calibration",
            "number.pawsync_feeder_tank_refill_weight",
        ],
        "switch": [
            "switch.pawsync_feeder_intelligent_feeding_leftover_deduction",
            "switch.pawsync_feeder_slow_feed_mode",
            "switch.pawsync_feeder_sleep_mode",
        ],
    }.get(domain, [])

    entry = MagicMock()
    entry.title = "Pawsync Feeder"
    entry.data = {
        "feeder_info": {
            "mac": "11:22:33:44:55:66",
            "name": "Pawsync Feeder",
        }
    }

    mock_backup = {
        "cid": "cid_test_001",
        "single_weight_g": 8.5,
        "intelligent_feeding": True,
        "slow_feed": True,
        "sleep_mode": False,
        "bucket_surplus": 1750,
        "plans": [
            {
                "planId": 1,
                "detail": {
                    "meals": [
                        {"timeSec": 28800, "weight": 17, "repeat": 127},
                        {"timeSec": 64800, "weight": 25, "repeat": 62},
                    ]
                },
            }
        ],
    }

    success = await async_restore_cloud_settings(hass, entry, backup_data=mock_backup)
    assert success is True

    # Check number entity calls
    number_calls = [c for c in called_services if c[0] == "number"]
    assert any(
        c[1] == "set_value"
        and "grams_per_portion" in c[2]["entity_id"]
        and c[2]["value"] == 8.5
        for c in number_calls
    )
    assert any(
        c[1] == "set_value"
        and "tank_refill_weight" in c[2]["entity_id"]
        and c[2]["value"] == 1750.0
        for c in number_calls
    )

    # Check switch calls
    switch_calls = [c for c in called_services if c[0] == "switch"]
    assert any(
        c[1] == "turn_on" and "intelligent_feeding" in c[2]["entity_id"]
        for c in switch_calls
    )
    assert any(
        c[1] == "turn_on" and "slow_feed" in c[2]["entity_id"]
        for c in switch_calls
    )
    assert any(
        c[1] == "turn_off" and "sleep_mode" in c[2]["entity_id"]
        for c in switch_calls
    )

    # Check ESPHome meal schedule service calls
    esphome_calls = [c for c in called_services if c[0] == "esphome"]
    assert len(esphome_calls) == 2

    # Meal 1: 08:00, 17g / 8.5 = 2 portions, repeat 127 = All
    meal1 = esphome_calls[0][2]
    assert meal1["plan"] == 1
    assert meal1["meal"] == 1
    assert meal1["meal_time"] == "08:00"
    assert meal1["portions"] == 2
    assert meal1["days"] == "All"
    assert meal1["enabled"] is True

    # Meal 2: 18:00, 25g / 8.5 = 3 portions, repeat 62 = Weekdays
    meal2 = esphome_calls[1][2]
    assert meal2["plan"] == 1
    assert meal2["meal"] == 2
    assert meal2["meal_time"] == "18:00"
    assert meal2["portions"] == 3
    assert meal2["days"] == "Weekdays"
    assert meal2["enabled"] is True


@pytest.mark.asyncio
async def test_service_restore_cloud_backup_handler():
    """Verify pawsync.restore_cloud_backup service execution."""
    from custom_components.pawsync.services import async_setup_services

    hass = MagicMock()
    registered_services = {}

    def mock_register(domain, service, handler, schema=None):
        registered_services[service] = handler

    hass.services.has_service.return_value = False
    hass.services.async_register = mock_register

    mock_entry = MagicMock()
    mock_entry.entry_id = "entry_123"
    mock_entry.title = "Test Feeder"
    mock_entry.data = {"feeder_info": {"mac": "AABBCCDDEEFF"}}
    hass.config_entries.async_entries.return_value = [mock_entry]

    await async_setup_services(hass)
    assert "restore_cloud_backup" in registered_services

    handler = registered_services["restore_cloud_backup"]
    call = MagicMock()
    call.data = {"mac": "AA:BB:CC:DD:EE:FF"}

    with patch("custom_components.pawsync.restore_manager.async_restore_cloud_settings", new=AsyncMock(return_value=True)) as mock_restore:
        await handler(call)
        mock_restore.assert_called_once_with(hass, mock_entry)


@pytest.mark.asyncio
async def test_restore_cloud_settings_updates_entry_restored_flag():
    """Verify cloud_profile_restored flag is persisted to entry.data upon successful restore."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    entry = MagicMock()
    entry.title = "Pawsync Feeder"
    entry.data = {
        "feeder_info": {"mac": "11:22:33:44:55:66"},
    }

    mock_backup = {
        "single_weight_g": 8.0,
        "plans": [],
    }

    with patch("custom_components.pawsync.restore_manager.load_cloud_backup", return_value=mock_backup):
        success = await async_restore_cloud_settings(hass, entry)
        assert success is True
        hass.config_entries.async_update_entry.assert_called_once()
        _, kwargs = hass.config_entries.async_update_entry.call_args
        assert kwargs["data"]["cloud_profile_restored"] is True


@pytest.mark.asyncio
async def test_restore_cloud_settings_service_retry_discovers_service():
    """Verify service discovery retries and succeeds if service is delayed during startup."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    entry = MagicMock()
    entry.title = "Pawsync Feeder"
    entry.data = {
        "feeder_info": {"mac": "11:22:33:44:55:66"},
    }

    mock_backup = {
        "single_weight_g": 8.0,
        "plans": [
            {
                "detail": {
                    "meals": [{"timeSec": 28800, "weight": 16, "repeat": 127}]
                }
            }
        ],
    }

    # Simulate find_esphome_service returning None initially, then succeeding on retry
    service_lookups = [None, "pawsync_feeder_set_meal_schedule"]

    def mock_find_service(*args, **kwargs):
        if service_lookups:
            return service_lookups.pop(0)
        return "pawsync_feeder_set_meal_schedule"

    called_services = []

    async def mock_async_call(domain, service, data=None, blocking=True):
        called_services.append((domain, service, data))
        return True

    hass.services.async_call = mock_async_call

    with patch("custom_components.pawsync.restore_manager.load_cloud_backup", return_value=mock_backup), \
         patch("custom_components.pawsync.restore_manager.find_esphome_service", side_effect=mock_find_service), \
         patch("asyncio.sleep", new=AsyncMock()):
        success = await async_restore_cloud_settings(hass, entry)
        assert success is True
        assert len(called_services) == 1
        assert called_services[0][1] == "pawsync_feeder_set_meal_schedule"
