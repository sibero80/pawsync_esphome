"""Tests for PawSync Firmware Downloader and Binary Resolver."""

import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError

from custom_components.pawsync.firmware_downloader import (
    CONTAINER_MAGIC_BYTE,
    DEFAULT_OTA_REPO,
    MAX_CONTAINER_SIZE,
    MIN_CONTAINER_SIZE,
    OTA_BINARY_FILENAME,
    async_ensure_firmware_binary,
    get_firmware_cache_dir,
    get_local_firmware_candidates,
    validate_firmware_container,
)


def test_validate_firmware_container(tmp_path):
    """Test container validation rules."""
    # 1. Non-existent file
    assert validate_firmware_container(str(tmp_path / "nonexistent.bin")) is False

    # 2. File too small
    small_file = tmp_path / "too_small.bin"
    small_file.write_bytes(b"\x01" + b"\x00" * 100)
    assert validate_firmware_container(str(small_file)) is False

    # 3. File missing 0x01 header
    bad_header = tmp_path / "bad_header.bin"
    bad_header.write_bytes(b"\x00" * 600_000)
    assert validate_firmware_container(str(bad_header)) is False

    # 4. Valid container
    valid_file = tmp_path / "valid.bin"
    valid_file.write_bytes(bytes([CONTAINER_MAGIC_BYTE]) + b"\x00" * 600_000)
    assert validate_firmware_container(str(valid_file)) is True


@pytest.mark.asyncio
async def test_async_ensure_firmware_binary_local_hit(tmp_path):
    """Test using an existing local binary candidate without network activity."""
    hass = MagicMock()
    hass.config.config_dir = str(tmp_path)

    # Place a valid binary at /config/pawsync_ota_update.bin
    valid_local = tmp_path / OTA_BINARY_FILENAME
    valid_local.write_bytes(bytes([CONTAINER_MAGIC_BYTE]) + b"\x00" * 600_000)

    resolved_path = await async_ensure_firmware_binary(hass)
    assert resolved_path == str(valid_local)
    assert os.path.exists(resolved_path)


@pytest.mark.asyncio
async def test_async_ensure_firmware_binary_download_success(tmp_path):
    """Test downloading binary from upstream pawsync_ota repo on cache miss."""
    hass = MagicMock()
    hass.config.config_dir = str(tmp_path)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    valid_payload = bytes([CONTAINER_MAGIC_BYTE]) + b"\x55" * 600_000

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.read = AsyncMock(return_value=valid_payload)

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    resolved_path = await async_ensure_firmware_binary(
        hass,
        version="1.2.0",
        session=mock_session,
    )

    assert os.path.exists(resolved_path)
    assert os.path.basename(resolved_path) == OTA_BINARY_FILENAME
    assert os.path.getsize(resolved_path) == len(valid_payload)


@pytest.mark.asyncio
async def test_async_ensure_firmware_binary_download_failure(tmp_path):
    """Test HomeAssistantError raised when upstream download fails and no local copy exists."""
    hass = MagicMock()
    hass.config.config_dir = str(tmp_path)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    mock_resp = AsyncMock()
    mock_resp.status = 404

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    with pytest.raises(HomeAssistantError) as exc_info:
        await async_ensure_firmware_binary(
            hass,
            version="9.9.9",
            session=mock_session,
        )

    assert "Could not locate or download" in str(exc_info.value)
    assert DEFAULT_OTA_REPO in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_ensure_firmware_binary_sha256_pinning_success(tmp_path):
    """Test downloading binary with matching SHA-256 digest succeeds."""
    import hashlib
    hass = MagicMock()
    hass.config.config_dir = str(tmp_path)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    valid_payload = bytes([CONTAINER_MAGIC_BYTE]) + b"\x77" * 600_000
    expected_hash = hashlib.sha256(valid_payload).hexdigest()

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.read = AsyncMock(return_value=valid_payload)

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    resolved_path = await async_ensure_firmware_binary(
        hass,
        version="1.5.0",
        session=mock_session,
        expected_digest=f"sha256:{expected_hash}",
    )
    assert os.path.exists(resolved_path)


@pytest.mark.asyncio
async def test_async_ensure_firmware_binary_sha256_mismatch_rejects(tmp_path):
    """Test downloading binary with mismatched SHA-256 digest raises HomeAssistantError."""
    hass = MagicMock()
    hass.config.config_dir = str(tmp_path)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    tampered_payload = bytes([CONTAINER_MAGIC_BYTE]) + b"\x99" * 600_000

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.read = AsyncMock(return_value=tampered_payload)

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    with pytest.raises(HomeAssistantError, match="SHA-256 digest verification failed"):
        await async_ensure_firmware_binary(
            hass,
            version="1.5.0",
            session=mock_session,
            expected_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )


def test_get_firmware_cache_dir():
    """Test get_firmware_cache_dir helper."""
    hass = MagicMock()
    hass.config.config_dir = "/my_config"
    assert get_firmware_cache_dir(hass) == "/my_config/.storage/pawsync"


def test_validate_firmware_container_requires_psk_and_ota(tmp_path):
    """Test validate_firmware_container strictly requires both PSK and OTA placeholders when require_patchable=True."""
    from custom_components.pawsync.firmware_patcher import (
        SSID_PLACEHOLDER,
        PASS_PLACEHOLDER,
        NOISE_PSK_PLACEHOLDER,
        OTA_PASSWORD_PLACEHOLDER,
        package_vesync_ota_container,
        recalculate_esp32_checksum,
        recalculate_esp32_sha256,
    )
    import struct

    def make_container(include_psk: bool, include_ota: bool) -> bytes:
        payload = b"INIT_" + SSID_PLACEHOLDER + b"_MID_" + PASS_PLACEHOLDER
        if include_psk:
            payload += b"_PSK_" + NOISE_PSK_PLACEHOLDER
        if include_ota:
            payload += b"_OTA_" + OTA_PASSWORD_PLACEHOLDER
        payload += b"_TAIL"
        seg = struct.pack("<II", 0x3FFB0000, len(payload))
        raw = bytearray(24)
        raw[0] = 0xE9
        raw[1] = 1
        raw += seg + payload + bytearray(33)
        recalculate_esp32_checksum(raw)
        recalculate_esp32_sha256(raw)
        # Pad to >= MIN_CONTAINER_SIZE
        padded_raw = bytes(raw) + (b"\x00" * 550_000)
        return package_vesync_ota_container(padded_raw)

    # 1. Image with only Wi-Fi placeholders (stale v1.4.x)
    stale_file = tmp_path / "stale.bin"
    stale_file.write_bytes(make_container(include_psk=False, include_ota=False))
    assert validate_firmware_container(str(stale_file), require_patchable=False) is True
    assert validate_firmware_container(str(stale_file), require_patchable=True) is False

    # 2. Image with all Sprint 2 placeholders (v1.5.0-beta)
    valid_file = tmp_path / "valid_all.bin"
    valid_file.write_bytes(make_container(include_psk=True, include_ota=True))
    assert validate_firmware_container(str(valid_file), require_patchable=True) is True
