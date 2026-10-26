"""Tests for ESPHome YAML Provisioner."""

import os
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
