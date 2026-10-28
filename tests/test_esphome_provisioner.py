"""Tests for ESPHome YAML Provisioner."""

import os
import pytest
from custom_components.pawsync.esphome_provisioner import (
    generate_esphome_yaml,
    sanitize_filename,
)


def test_sanitize_filename():
    """Verify safe filename sanitization."""
    assert sanitize_filename("Living Room Feeder #1") == "living_room_feeder_1"
    assert sanitize_filename("Fluffy's Bowl!") == "fluffy_s_bowl"
    assert sanitize_filename("___test___") == "test"


def test_generate_esphome_yaml():
    """Verify generated YAML content."""
    # Test auto-generated credentials
    yaml_text = generate_esphome_yaml(
        device_name="pawsync-cat",
        friendly_name="Pawsync Cat Feeder",
        wifi_ssid="MyHomeNetwork",
        wifi_password="SecretPassword123",
        mac_address="AA:BB:CC:DD:EE:FF",
    )

    assert 'name: "pawsync-cat"' in yaml_text
    assert 'friendly_name: "Pawsync Cat Feeder"' in yaml_text
    assert 'ssid: "MyHomeNetwork"' in yaml_text
    assert 'password: "SecretPassword123"' in yaml_text
    assert "pawsync_base:" in yaml_text
    assert "https://github.com/sibero80/pawsync_esphome" in yaml_text
    assert "# Device MAC: AA:BB:CC:DD:EE:FF" in yaml_text
    assert 'key: "' in yaml_text
    assert 'password: "' in yaml_text

    # Test explicit credential overrides
    custom_yaml = generate_esphome_yaml(
        device_name="pawsync-custom",
        friendly_name="Pawsync Custom Feeder",
        wifi_ssid="MyHomeNetwork",
        wifi_password="SecretPassword123",
        mac_address="AA:BB:CC:DD:EE:FF",
        noise_psk="CUSTOM_NOISE_PSK_KEY_12345678901234567890=",
        ota_password="custom_ota_password_123",
    )
    assert 'key: "CUSTOM_NOISE_PSK_KEY_12345678901234567890="' in custom_yaml
    assert 'password: "custom_ota_password_123"' in custom_yaml


@pytest.mark.asyncio
async def test_async_auto_adopt_esphome_existing():
    """Verify auto-adopt returns True when entry already exists."""
    from unittest.mock import MagicMock
    from custom_components.pawsync.esphome_provisioner import async_auto_adopt_esphome

    hass = MagicMock()
    mock_entry = MagicMock()
    mock_entry.data = {"host": "192.168.1.45"}
    mock_entry.title = "Pawsync Feeder"
    mock_entry.entry_id = "test_entry_123"
    hass.config_entries.async_entries.return_value = [mock_entry]

    success = await async_auto_adopt_esphome(
        hass=hass,
        host="192.168.1.45",
        mac="AA:BB:CC:DD:EE:FF",
        max_attempts=1,
    )
    assert success is True

