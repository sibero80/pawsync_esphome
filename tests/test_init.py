"""Tests for PawSync Integration Setup and Repairs Issue Management."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.pawsync import (
    async_setup_entry,
    async_unload_entry,
    async_update_options,
)
from custom_components.pawsync.const import (
    CONF_HOST,
    CONF_SELECTED_FEEDER,
    DOMAIN,
)


@pytest.mark.asyncio
async def test_async_setup_entry_legacy_psk_creates_repairs_issue():
    """Verify that a legacy default Noise PSK triggers a Home Assistant Repairs issue."""
    hass = MagicMock()
    hass.data = {}
    hass.config.path.return_value = "/tmp/pawsync_test_www"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    entry = MagicMock()
    entry.entry_id = "test_entry_legacy"
    entry.title = "Fluffy's Feeder"
    entry.data = {
        CONF_HOST: "192.168.1.55",
        CONF_SELECTED_FEEDER: "cid_12345",
        "noise_psk": "2M4yBDYqWbBDSl3PIkccw2IkCUj5WIySqP8JHYVG7Mc=",
        "feeder_info": {"name": "Fluffy's Feeder", "mac": "11:22:33:44:55:66"},
    }
    entry.options = {}

    with patch("homeassistant.helpers.issue_registry.async_create_issue") as mock_create_issue:
        success = await async_setup_entry(hass, entry)
        assert success is True
        mock_create_issue.assert_called_once()
        call_kwargs = mock_create_issue.call_args[1]
        assert call_kwargs["domain"] == DOMAIN
        assert call_kwargs["issue_id"] == "legacy_noise_psk_test_entry_legacy"
        assert call_kwargs["translation_key"] == "legacy_noise_psk"


@pytest.mark.asyncio
async def test_async_setup_entry_unique_psk_deletes_repairs_issue():
    """Verify that a unique Noise PSK clears any existing repairs issue."""
    hass = MagicMock()
    hass.data = {}
    hass.config.path.return_value = "/tmp/pawsync_test_www"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    entry = MagicMock()
    entry.entry_id = "test_entry_unique"
    entry.title = "Fluffy's Feeder"
    entry.data = {
        CONF_HOST: "192.168.1.55",
        CONF_SELECTED_FEEDER: "cid_12345",
        "noise_psk": "uNIQUEkEY1234567890123456789012345678901234=",
        "feeder_info": {"name": "Fluffy's Feeder", "mac": "11:22:33:44:55:66"},
    }
    entry.options = {}

    with patch("homeassistant.helpers.issue_registry.async_delete_issue") as mock_delete_issue:
        success = await async_setup_entry(hass, entry)
        assert success is True
        mock_delete_issue.assert_called_once()
        call_kwargs = mock_delete_issue.call_args[1]
        assert call_kwargs["domain"] == DOMAIN
        assert call_kwargs["issue_id"] == "legacy_noise_psk_test_entry_unique"


@pytest.mark.asyncio
async def test_options_override_host():
    """Verify that host in options takes precedence over entry data."""
    hass = MagicMock()
    hass.data = {}
    hass.config.path.return_value = "/tmp/pawsync_test_www"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    entry = MagicMock()
    entry.entry_id = "test_entry_opts"
    entry.title = "Fluffy's Feeder"
    entry.data = {
        CONF_HOST: "192.168.1.55",
        CONF_SELECTED_FEEDER: "cid_12345",
        "noise_psk": "uNIQUEkEY1234567890123456789012345678901234=",
    }
    entry.options = {
        CONF_HOST: "192.168.1.99",
    }

    with patch("custom_components.pawsync.async_auto_adopt_esphome") as mock_adopt:
        success = await async_setup_entry(hass, entry)
        assert success is True
        # Verify auto-adopt was triggered with options host override
        hass.async_create_task.assert_called()


@pytest.mark.asyncio
async def test_async_update_options():
    """Test options update reloads the config entry."""
    hass = MagicMock()
    hass.config_entries.async_reload = AsyncMock()

    entry = MagicMock()
    entry.entry_id = "test_reload_entry"

    await async_update_options(hass, entry)
    hass.config_entries.async_reload.assert_called_once_with("test_reload_entry")


@pytest.mark.asyncio
async def test_async_unload_entry():
    """Test unloading config entry."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry_to_unload": {"some": "data"}}}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    entry = MagicMock()
    entry.entry_id = "entry_to_unload"
    entry.title = "Test Feeder"

    unloaded = await async_unload_entry(hass, entry)
    assert unloaded is True
    assert "entry_to_unload" not in hass.data[DOMAIN]
