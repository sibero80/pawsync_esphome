"""Unit tests for PawSync Firmware Update platform and ESPHome OTA flasher."""

import asyncio
import hashlib
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.pawsync.const import DOMAIN, VERSION
from custom_components.pawsync.espota_client import (
    MAGIC_BYTES,
    RESPONSE_AUTH_OK,
    RESPONSE_BIN_MD5_OK,
    RESPONSE_CHUNK_OK,
    RESPONSE_OK,
    RESPONSE_RECEIVE_OK,
    RESPONSE_UPDATE_END_OK,
    RESPONSE_UPDATE_PREPARE_OK,
    async_flash_esphome_ota,
    sanitize_firmware_binary,
)
from custom_components.pawsync.update import (
    PawSyncFirmwareUpdateEntity,
    async_setup_entry,
)


@pytest.mark.asyncio
async def test_update_entity_installed_and_latest_version():
    """Test installed version detection and latest version reporting."""
    hass = MagicMock()
    entry = MagicMock()
    entry.title = "Pawsync Feeder"
    entry.data = {
        "feeder_info": {"mac": "AA:BB:CC:DD:EE:FF", "name": "Kitchen Feeder"},
        "host": "192.168.1.150",
    }

    # Case 1: Default when not yet updated
    hass.config_entries.async_entries.return_value = []
    dev_reg = MagicMock()
    dev_reg.async_get_device.return_value = None
    with patch("homeassistant.helpers.device_registry.async_get", return_value=dev_reg):
        entity = PawSyncFirmwareUpdateEntity(hass, entry)
        assert entity.installed_version == "1.0.8"
        assert entity.latest_version == VERSION
        assert entity.latest_version > entity.installed_version

    # Case 2: ESPHome device info reports project_version
    esphome_entry = MagicMock()
    esphome_entry.unique_id = "aabbccddeeff"
    esphome_entry.data = {"host": "192.168.1.150"}
    dev_info = MagicMock()
    dev_info.project_version = "1.0.8"
    esphome_entry.runtime_data.device_info = dev_info
    hass.config_entries.async_entries.return_value = [esphome_entry]

    with patch("homeassistant.helpers.device_registry.async_get", return_value=dev_reg):
        entity = PawSyncFirmwareUpdateEntity(hass, entry)
        assert entity.installed_version == "1.0.8"

    # Case 3: Already updated to latest version
    dev_info.project_version = VERSION
    with patch("homeassistant.helpers.device_registry.async_get", return_value=dev_reg):
        entity = PawSyncFirmwareUpdateEntity(hass, entry)
        assert entity.installed_version == VERSION
        assert entity.installed_version == entity.latest_version


@pytest.mark.asyncio
async def test_update_entity_release_notes():
    """Test fetching release notes."""
    hass = MagicMock()
    entry = MagicMock()
    entry.title = "Feeder"
    entry.data = {}

    entity = PawSyncFirmwareUpdateEntity(hass, entry)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert len(notes) > 0


@pytest.mark.asyncio
async def test_esphome_ota_flasher_protocol():
    """Test full ESPHome OTA v2 protocol handshake and streaming over mock TCP socket."""
    # Create test dummy payload starting with ESP32 magic byte 0xE9
    payload = b"\xe9" + (b"DUMMY_ESPHOME_FIRMWARE_BINARY_BYTES" * 300)

    server_received_bytes = bytearray()
    server_auth_seen = False
    server_prepare_seen = False
    server_md5_seen = False

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        nonlocal server_auth_seen, server_prepare_seen, server_md5_seen

        # 1. Read magic bytes (5 bytes)
        magic = await reader.readexactly(5)
        assert magic == MAGIC_BYTES

        # 2. Respond with version 2
        writer.write(bytes([RESPONSE_OK, 0x02]))
        await writer.drain()

        # 3. Read client features
        features = await reader.readexactly(1)
        # Respond with features
        writer.write(bytes([0x46]))  # RESPONSE_SUPPORTS_COMPRESSION
        await writer.drain()

        # 4. Respond with Auth OK
        writer.write(bytes([RESPONSE_AUTH_OK]))
        await writer.drain()
        server_auth_seen = True

        # 5. Read binary size (4 bytes)
        size_bytes = await reader.readexactly(4)
        upload_size = int.from_bytes(size_bytes, "big")
        assert upload_size == len(payload)

        # 6. Send prepare OK
        writer.write(bytes([RESPONSE_UPDATE_PREPARE_OK]))
        await writer.drain()
        server_prepare_seen = True

        # 7. Read MD5 (32 bytes hex)
        md5_bytes = await reader.readexactly(32)
        expected_md5 = hashlib.md5(payload).hexdigest().encode("ascii")
        assert md5_bytes == expected_md5
        server_md5_seen = True

        # 8. Send MD5 OK
        writer.write(bytes([RESPONSE_BIN_MD5_OK]))
        await writer.drain()

        # 9. Read chunks (8192 bytes) and ack each
        remaining = upload_size
        while remaining > 0:
            to_read = min(8192, remaining)
            chunk = await reader.readexactly(to_read)
            server_received_bytes.extend(chunk)
            remaining -= len(chunk)
            writer.write(bytes([RESPONSE_CHUNK_OK]))
            await writer.drain()

        # 10. Send commit / end OK
        writer.write(bytes([RESPONSE_RECEIVE_OK]))
        writer.write(bytes([RESPONSE_UPDATE_END_OK]))
        await writer.drain()

        # 11. Read final OK
        end_ack = await reader.readexactly(1)
        assert end_ack[0] == RESPONSE_OK

        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    progress_reports = []

    def on_prog(pct):
        progress_reports.append(pct)

    async with server:
        success = await async_flash_esphome_ota(
            host="127.0.0.1",
            firmware_binary=payload,
            port=server_port,
            on_progress=on_prog,
            timeout=5.0,
        )

    assert success is True
    assert server_auth_seen is True
    assert server_prepare_seen is True
    assert server_md5_seen is True
    assert bytes(server_received_bytes) == payload
    assert len(progress_reports) > 0
    assert progress_reports[-1] == 1.0


@pytest.mark.asyncio
async def test_update_install_execution():
    """Test update entity async_install flow end-to-end."""
    hass = MagicMock()
    hass.config.config_dir = "/tmp"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn: fn())

    entry = MagicMock()
    entry.title = "Pawsync Feeder"
    entry.data = {
        "feeder_info": {"mac": "AA:BB:CC:DD:EE:FF", "name": "Kitchen Feeder"},
        "host": "192.168.1.50",
    }

    dev_reg = MagicMock()
    mock_dev = MagicMock()
    mock_dev.id = "dev_123"
    mock_dev.sw_version = None
    dev_reg.async_get_device.return_value = mock_dev

    with patch("custom_components.pawsync.update.dr.async_get", return_value=dev_reg), \
         patch("custom_components.pawsync.update.async_flash_esphome_ota", new_callable=AsyncMock) as mock_flash:
        mock_flash.return_value = True

        entity = PawSyncFirmwareUpdateEntity(hass, entry)
        assert entity.installed_version == "1.0.8"

        await entity.async_install()

        assert mock_flash.called
        assert entity.installed_version == entity.latest_version
        assert dev_reg.async_update_device.called


def test_sanitize_firmware_binary():
    """Test stripping VeSync 129-byte container header for native ESPHome OTA."""
    # Pure ESP32 image starting with 0xE9
    pure_image = b"\xe9\x06\x02\x2f" + (b"\x00" * 1000)
    assert sanitize_firmware_binary(pure_image) == pure_image

    # VeSync container wrapped image: 129 bytes header + pure ESP32 image
    container_header = b"\x01\x7e\xd8\xe5" + (b"\xaa" * 125)
    assert len(container_header) == 129
    wrapped_image = container_header + pure_image
    sanitized = sanitize_firmware_binary(wrapped_image)
    assert sanitized == pure_image
    assert len(sanitized) == len(pure_image)
    assert sanitized[0] == 0xE9

