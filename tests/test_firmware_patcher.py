"""Tests for dynamic in-memory firmware patcher."""

import pytest
from custom_components.pawsync.firmware_patcher import (
    SSID_PLACEHOLDER,
    PASS_PLACEHOLDER,
    can_patch_firmware,
    patch_raw_esp32_credentials,
    package_vesync_ota_container,
    patch_container_firmware,
    recalculate_esp32_checksum,
    recalculate_esp32_sha256,
)


def test_can_patch_firmware_detection():
    """Verify detection of patchable firmware."""
    fake_raw = b"\x00" * 100 + SSID_PLACEHOLDER + b"\x00" * 50 + PASS_PLACEHOLDER + b"\x00" * 100
    assert can_patch_firmware(fake_raw) is True

    # VeSync container header + payload
    fake_container = bytes([0x01]) + b"\x00" * 128 + fake_raw
    assert can_patch_firmware(fake_container) is True

    # Missing placeholders
    assert can_patch_firmware(b"\x00" * 300) is False


def test_patch_container_firmware_end_to_end(tmp_path):
    """Verify end-to-end container patching with checksum verification."""
    # Read actual compiled binary from repo if present
    import os
    repo_bin = "/root/pawsync_ota/pawsync_ota_update.bin"
    if not os.path.exists(repo_bin):
        pytest.skip("Base binary not found")

    with open(repo_bin, "rb") as f:
        orig_container = f.read()

    assert can_patch_firmware(orig_container) is True

    patched = patch_container_firmware(
        orig_container,
        ssid="MyLivingRoomWifi",
        password="SuperSecurePassword123!",
    )

    assert len(patched) == len(orig_container)
    assert b"MyLivingRoomWifi" in patched
    assert b"SuperSecurePassword123!" in patched
    assert SSID_PLACEHOLDER not in patched
    assert PASS_PLACEHOLDER not in patched

    # Check VeSync container header byte
    assert patched[0] == 0x01
    # Check ESP32 magic byte
    assert patched[129] == 0xE9
