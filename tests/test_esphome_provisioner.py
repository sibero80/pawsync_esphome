"""Tests for ESPHome YAML Provisioner."""

import os
import pytest
from custom_components.pawsync.esphome_provisioner import (
    async_write_feeder_secrets,
    generate_esphome_yaml,
    sanitize_filename,
    sanitize_mac,
    write_feeder_secrets_sync,
)


def test_sanitize_filename():
    """Verify safe filename sanitization."""
    assert sanitize_filename("Living Room Feeder #1") == "living_room_feeder_1"
    assert sanitize_filename("Fluffy's Bowl!") == "fluffy_s_bowl"
    assert sanitize_filename("___test___") == "test"


def test_sanitize_mac():
    """Verify clean MAC address normalization."""
    assert sanitize_mac("AA:BB:CC:DD:EE:FF") == "aabbccddeeff"
    assert sanitize_mac("aa-bb-cc-dd-ee-ff") == "aabbccddeeff"
    assert sanitize_mac("AABBCCDDEEFF") == "aabbccddeeff"
    assert sanitize_mac("") == ""


def test_generate_esphome_yaml_with_mac():
    """Verify generated YAML content with MAC uses !secret and Option C SoftAP."""
    yaml_text = generate_esphome_yaml(
        device_name="pawsync-cat",
        friendly_name="Pawsync Cat Feeder",
        wifi_ssid="MyHomeNetwork",
        wifi_password="SecretPassword123",
        mac_address="AA:BB:CC:DD:EE:FF",
    )

    assert 'name: "pawsync-cat"' in yaml_text
    assert 'friendly_name: "Pawsync Cat Feeder"' in yaml_text
    assert "ssid: !secret feeder_aabbccddeeff_wifi_ssid" in yaml_text
    assert "password: !secret feeder_aabbccddeeff_wifi_password" in yaml_text
    assert "key: !secret feeder_aabbccddeeff_noise_psk" in yaml_text
    assert "password: !secret feeder_aabbccddeeff_ota_password" in yaml_text
    assert "pawsync_base:" in yaml_text
    assert "https://github.com/sibero80/pawsync_esphome" in yaml_text
    assert "# Device MAC: AA:BB:CC:DD:EE:FF" in yaml_text

    # Option C SoftAP verification (T9-S2-SAP)
    assert 'ssid: "Pawsync-Feeder-Fallback"' in yaml_text
    assert 'password: "pawsync1234"' in yaml_text


def test_generate_esphome_yaml_without_mac():
    """Verify fallback when MAC address is not provided."""
    yaml_text = generate_esphome_yaml(
        device_name="pawsync-generic",
        friendly_name="Pawsync Feeder",
        wifi_ssid="MyHomeNetwork",
        wifi_password="SecretPassword123",
        mac_address="",
        noise_psk="CUSTOM_KEY_123=",
        ota_password="custom_ota_pass",
    )
    assert 'ssid: "MyHomeNetwork"' in yaml_text
    assert 'password: "SecretPassword123"' in yaml_text
    assert 'key: "CUSTOM_KEY_123="' in yaml_text
    assert 'password: "custom_ota_pass"' in yaml_text


def test_secrets_yaml_atomic_merge_and_permissions(tmp_path):
    """Verify secrets.yaml is written with mode 0600 and non-destructive multi-device merge."""
    secrets_file = tmp_path / "secrets.yaml"

    # Pre-populate with existing user secret
    import yaml
    secrets_file.write_text("existing_user_key: existing_user_value\n", encoding="utf-8")

    # Write secrets for Feeder 1
    write_feeder_secrets_sync(
        config_dir_or_path=tmp_path,
        mac="AA:BB:CC:DD:EE:01",
        secrets_dict={
            "wifi_ssid": "HomeWiFi",
            "wifi_password": "Pass1",
            "noise_psk": "PSK_FEEDER_1_BASE64_KEY_123456789012345678901=",
            "ota_password": "ota_pass_feeder_1",
        },
        secrets_path=secrets_file,
    )

    # Check mode 0600
    stat_mode = os.stat(secrets_file).st_mode & 0o777
    assert stat_mode == 0o600

    # Write secrets for Feeder 2
    write_feeder_secrets_sync(
        config_dir_or_path=tmp_path,
        mac="AA:BB:CC:DD:EE:02",
        secrets_dict={
            "wifi_ssid": "HomeWiFi",
            "wifi_password": "Pass2",
            "noise_psk": "PSK_FEEDER_2_BASE64_KEY_123456789012345678902=",
            "ota_password": "ota_pass_feeder_2",
        },
        secrets_path=secrets_file,
    )

    # Verify all keys exist without collision
    loaded = yaml.safe_load(secrets_file.read_text(encoding="utf-8"))
    assert loaded["existing_user_key"] == "existing_user_value"
    assert loaded["feeder_aabbccddee01_wifi_ssid"] == "HomeWiFi"
    assert loaded["feeder_aabbccddee01_noise_psk"] == "PSK_FEEDER_1_BASE64_KEY_123456789012345678901="
    assert loaded["feeder_aabbccddee01_ota_password"] == "ota_pass_feeder_1"
    assert loaded["feeder_aabbccddee02_wifi_ssid"] == "HomeWiFi"
    assert loaded["feeder_aabbccddee02_noise_psk"] == "PSK_FEEDER_2_BASE64_KEY_123456789012345678902="
    assert loaded["feeder_aabbccddee02_ota_password"] == "ota_pass_feeder_2"

    # Verify file permissions remain 0600
    assert os.stat(secrets_file).st_mode & 0o777 == 0o600


def test_secrets_yaml_corrupted_refuses_overwrite_and_preserves_backup(tmp_path):
    """Verify write_feeder_secrets_sync refuses to overwrite malformed secrets and creates backup."""
    secrets_file = tmp_path / "secrets.yaml"
    # Write invalid YAML syntax
    secrets_file.write_text("invalid_yaml: [unclosed_bracket\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Cannot merge secrets"):
        write_feeder_secrets_sync(
            config_dir_or_path=tmp_path,
            mac="AA:BB:CC:DD:EE:01",
            secrets_dict={"wifi_ssid": "TestSSID"},
            secrets_path=secrets_file,
        )

    # Ensure original corrupted file was NOT deleted/emptied
    assert "invalid_yaml: [unclosed_bracket" in secrets_file.read_text(encoding="utf-8")

    # Ensure timestamped backup was created
    bak_files = list(tmp_path.glob("secrets.yaml.bak_*"))
    assert len(bak_files) >= 1
    assert "invalid_yaml: [unclosed_bracket" in bak_files[0].read_text(encoding="utf-8")


def test_secrets_yaml_fallback_unscoped_keys(tmp_path):
    """Verify fallback unscoped keys are populated for pawsync.yaml package compilation."""
    secrets_file = tmp_path / "secrets.yaml"

    import yaml
    write_feeder_secrets_sync(
        config_dir_or_path=tmp_path,
        mac="AA:BB:CC:11:22:33",
        secrets_dict={
            "wifi_ssid": "MainWiFi",
            "wifi_password": "MainPassword",
            "noise_psk": "FEEDER_PSK_BASE64_KEY_123456789012345678901234=",
            "ota_password": "ota_password_123",
        },
        secrets_path=secrets_file,
    )

    loaded = yaml.safe_load(secrets_file.read_text(encoding="utf-8"))
    # MAC-scoped keys
    assert loaded["feeder_aabbcc112233_wifi_ssid"] == "MainWiFi"
    assert loaded["feeder_aabbcc112233_noise_psk"] == "FEEDER_PSK_BASE64_KEY_123456789012345678901234="
    # Fallback unscoped keys for package imports
    assert loaded["api_encryption_key"] == "FEEDER_PSK_BASE64_KEY_123456789012345678901234="
    assert loaded["ota_password"] == "ota_password_123"
    assert loaded["wifi_ssid"] == "MainWiFi"
    assert loaded["wifi_password"] == "MainPassword"


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


def test_read_feeder_secrets_sync(tmp_path):
    """Test reading feeder-scoped and unscoped secrets."""
    from custom_components.pawsync.esphome_provisioner import (
        read_feeder_secrets_sync,
        write_feeder_secrets_sync,
    )

    secrets_file = tmp_path / "secrets.yaml"
    write_feeder_secrets_sync(
        config_dir_or_path=tmp_path,
        mac="94:A9:90:4C:18:D8",
        secrets_dict={
            "wifi_ssid": "SecretSSID",
            "wifi_password": "SecretPassword",
            "noise_psk": "MyFeederPSK123=",
            "ota_password": "MyOtaPassword456",
        },
        secrets_path=secrets_file,
    )

    # 1. Read with matching MAC
    secrets = read_feeder_secrets_sync(tmp_path, mac="94:A9:90:4C:18:D8", secrets_path=secrets_file)
    assert secrets["wifi_ssid"] == "SecretSSID"
    assert secrets["wifi_password"] == "SecretPassword"
    assert secrets["noise_psk"] == "MyFeederPSK123="
    assert secrets["ota_password"] == "MyOtaPassword456"

    # 2. Read with different MAC falls back to unscoped keys
    other_secrets = read_feeder_secrets_sync(tmp_path, mac="11:22:33:44:55:66", secrets_path=secrets_file)
    assert other_secrets["wifi_ssid"] == "SecretSSID"
    assert other_secrets["wifi_password"] == "SecretPassword"
    assert other_secrets["noise_psk"] == "MyFeederPSK123="
    assert other_secrets["ota_password"] == "MyOtaPassword456"

    # 3. Non-existent file returns empty dict
    non_existent = read_feeder_secrets_sync(tmp_path / "non_existent", mac="11:22:33")
    assert non_existent == {}

