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
    RESPONSE_REQUEST_SHA256_AUTH,
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
    """Test update entity async_install flow end-to-end with credential patching."""
    hass = MagicMock()
    hass.config.config_dir = "/tmp"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))

    entry = MagicMock()
    entry.title = "Pawsync Feeder"
    entry.data = {
        "feeder_info": {"mac": "AA:BB:CC:DD:EE:FF", "name": "Kitchen Feeder"},
        "host": "192.168.1.50",
        "ssid": "MyWiFi",
        "wifi_password": "MyPass",
        "noise_psk": "MyFeederPSK123=",
        "ota_password": "MyOtaPassword456",
    }
    entry.options = {}

    dev_reg = MagicMock()
    mock_dev = MagicMock()
    mock_dev.id = "dev_123"
    mock_dev.sw_version = None
    dev_reg.async_get_device.return_value = mock_dev

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
        tf.write(b"\x01" + (b"\x00" * 128) + b"\xe9" + (b"\x00" * 1000))
        dummy_fw = tf.name

    try:
        with patch("custom_components.pawsync.update.dr.async_get", return_value=dev_reg), \
             patch("custom_components.pawsync.update.async_ensure_firmware_binary", new_callable=AsyncMock, return_value=dummy_fw), \
             patch("custom_components.pawsync.update.patch_raw_esp32_credentials", return_value=b"\xe9" + (b"\x00" * 1000)) as mock_patch, \
             patch("custom_components.pawsync.update.async_flash_esphome_ota", new_callable=AsyncMock) as mock_flash:
            mock_flash.return_value = True

            entity = PawSyncFirmwareUpdateEntity(hass, entry)
            assert entity.installed_version == "1.0.8"

            await entity.async_install()

            assert mock_patch.called
            # Verify credentials were passed to patch_raw_esp32_credentials
            assert mock_patch.call_args.kwargs["ssid"] == "MyWiFi"
            assert mock_patch.call_args.kwargs["password"] == "MyPass"
            assert mock_patch.call_args.kwargs["noise_psk"] == "MyFeederPSK123="
            assert mock_patch.call_args.kwargs["ota_password"] == "MyOtaPassword456"

            assert mock_flash.called
            assert entity.installed_version == entity.latest_version
            assert dev_reg.async_update_device.called
    finally:
        if os.path.exists(dummy_fw):
            os.remove(dummy_fw)


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


@pytest.mark.asyncio
async def test_esphome_ota_flasher_sha256_auth_protocol():
    """Test ESPHome OTA password authentication handshake (SHA256 challenge-response)."""
    payload = b"\xe9" + (b"SECURE_AUTH_FIRMWARE" * 50)
    test_password = "MySecureOtaPass!"
    auth_verified = False

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        nonlocal auth_verified

        # 1. Read magic bytes
        magic = await reader.readexactly(5)
        assert magic == MAGIC_BYTES

        # 2. Respond version 2
        writer.write(bytes([RESPONSE_OK, 0x02]))
        await writer.drain()

        # 3. Read client features
        await reader.readexactly(1)
        writer.write(bytes([0x46]))
        await writer.drain()

        # 4. Respond with Request SHA256 Auth + 64 hex byte nonce
        server_nonce = "1234567890abcdef" * 4
        writer.write(bytes([RESPONSE_REQUEST_SHA256_AUTH]) + server_nonce.encode("ascii"))
        await writer.drain()

        # Read 128 bytes (64B cnonce + 64B response)
        auth_bytes = await reader.readexactly(128)
        cnonce = auth_bytes[:64].decode("ascii")
        client_hash = auth_bytes[64:].decode("ascii")

        to_hash = test_password.encode("utf-8") + server_nonce.encode("ascii") + cnonce.encode("ascii")
        expected_hash = hashlib.sha256(to_hash).hexdigest()
        assert client_hash == expected_hash
        auth_verified = True

        # Send Auth OK
        writer.write(bytes([RESPONSE_AUTH_OK]))
        await writer.drain()

        # Read size
        await reader.readexactly(4)
        writer.write(bytes([RESPONSE_UPDATE_PREPARE_OK]))
        await writer.drain()

        # Read MD5
        await reader.readexactly(32)
        writer.write(bytes([RESPONSE_BIN_MD5_OK]))
        await writer.drain()

        # Read chunks
        remaining = len(payload)
        while remaining > 0:
            chunk = await reader.readexactly(min(8192, remaining))
            remaining -= len(chunk)
            writer.write(bytes([RESPONSE_CHUNK_OK]))
            await writer.drain()

        writer.write(bytes([RESPONSE_RECEIVE_OK, RESPONSE_UPDATE_END_OK]))
        await writer.drain()
        await reader.readexactly(1)

        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]
    server_task = asyncio.create_task(server.serve_forever())

    try:
        success = await async_flash_esphome_ota(
            host="127.0.0.1",
            firmware_binary=payload,
            port=server_port,
            ota_password=test_password,
        )
        assert success is True
        assert auth_verified is True
    finally:
        server.close()
        await server.wait_closed()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_esphome_ota_flasher_sha256_fallback_auth():
    """Test OTA fallback authentication using placeholder password when primary password fails."""
    payload = b"\xe9" + (b"FALLBACK_AUTH_FIRMWARE" * 50)
    primary_wrong_password = "WrongPassword123"
    fallback_correct_password = "PLACEHOLDER_OTA_PASSWORD_32B____"
    fallback_auth_seen = False

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        nonlocal fallback_auth_seen

        magic = await reader.readexactly(5)
        assert magic == MAGIC_BYTES

        writer.write(bytes([RESPONSE_OK, 0x02]))
        await writer.drain()

        await reader.readexactly(1)
        writer.write(bytes([0x46]))
        await writer.drain()

        server_nonce = "abcdef1234567890" * 4
        writer.write(bytes([RESPONSE_REQUEST_SHA256_AUTH]) + server_nonce.encode("ascii"))
        await writer.drain()

        auth_bytes = await reader.readexactly(128)
        cnonce = auth_bytes[:64].decode("ascii")
        client_hash = auth_bytes[64:].decode("ascii")

        # Verify whether client tried fallback password
        expected_hash = hashlib.sha256(
            fallback_correct_password.encode("utf-8") + server_nonce.encode("ascii") + cnonce.encode("ascii")
        ).hexdigest()

        if client_hash == expected_hash:
            fallback_auth_seen = True
            writer.write(bytes([RESPONSE_AUTH_OK]))
            await writer.drain()

            await reader.readexactly(4)
            writer.write(bytes([RESPONSE_UPDATE_PREPARE_OK]))
            await writer.drain()

            await reader.readexactly(32)
            writer.write(bytes([RESPONSE_BIN_MD5_OK]))
            await writer.drain()

            remaining = len(payload)
            while remaining > 0:
                chunk = await reader.readexactly(min(8192, remaining))
                remaining -= len(chunk)
                writer.write(bytes([RESPONSE_CHUNK_OK]))
                await writer.drain()

            writer.write(bytes([RESPONSE_RECEIVE_OK, RESPONSE_UPDATE_END_OK]))
            await writer.drain()
            await reader.readexactly(1)
        else:
            # Reject primary wrong password
            writer.write(bytes([0xFF]))
            await writer.drain()

        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]
    server_task = asyncio.create_task(server.serve_forever())

    try:
        success = await async_flash_esphome_ota(
            host="127.0.0.1",
            firmware_binary=payload,
            port=server_port,
            ota_password=primary_wrong_password,
        )
        assert success is True
        assert fallback_auth_seen is True
    finally:
        server.close()
        await server.wait_closed()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_service_flash_latest_firmware():
    """Test flash_latest_firmware service handler."""
    from custom_components.pawsync.services import async_setup_services

    hass = MagicMock()
    registered_services = {}

    def mock_register(domain, service, handler, schema=None):
        registered_services[service] = handler

    hass.services.has_service.return_value = False
    hass.services.async_register = mock_register

    entry = MagicMock()
    entry.title = "Test Feeder"
    entry.data = {
        "feeder_info": {"mac": "94:A9:90:4C:18:D8", "ip": "192.168.1.45"},
        "mac_address": "94:A9:90:4C:18:D8",
        "host": "192.168.1.45",
    }
    hass.config_entries.async_entries.return_value = [entry]

    await async_setup_services(hass)
    assert "flash_latest_firmware" in registered_services

    call = MagicMock()
    call.data = {"host": "192.168.1.45"}

    with patch("custom_components.pawsync.update.PawSyncFirmwareUpdateEntity.async_install", new_callable=AsyncMock) as mock_install:
        await registered_services["flash_latest_firmware"](call)
        assert mock_install.called


@pytest.mark.asyncio
async def test_update_inherits_and_syncs_esphome_entry_key():
    """Test update inherits noise_psk from active ESPHome entry and auto-syncs."""
    hass = MagicMock()
    hass.config.config_dir = "/tmp"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    hass.config_entries.async_reload = AsyncMock()

    # Active ESPHome integration entry
    esphome_entry = MagicMock()
    esphome_entry.entry_id = "esphome_entry_123"
    esphome_entry.title = "Smart Pet Feeder"
    esphome_entry.unique_id = "aabbccddeeff"
    esphome_entry.data = {
        "host": "192.168.1.50",
        "noise_psk": "ActiveESPHomeKey123=",
        "password": "OldOtaPassword",
    }

    def mock_async_entries(domain):
        if domain == "esphome":
            return [esphome_entry]
        return []

    hass.config_entries.async_entries = mock_async_entries

    # PawSync entry without noise_psk
    pawsync_entry = MagicMock()
    pawsync_entry.title = "Pawsync Feeder"
    pawsync_entry.data = {
        "feeder_info": {"mac": "AA:BB:CC:DD:EE:FF", "name": "Kitchen Feeder"},
        "host": "192.168.1.50",
        "ssid": "MyWiFi",
        "wifi_password": "MyPass",
        "ota_password": "NewOtaPassword",
    }
    pawsync_entry.options = {}

    dev_reg = MagicMock()
    mock_dev = MagicMock()
    mock_dev.id = "dev_123"
    dev_reg.async_get_device.return_value = mock_dev

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
        tf.write(b"\x01" + (b"\x00" * 128) + b"\xe9" + (b"\x00" * 1000))
        dummy_fw = tf.name

    try:
        with patch("custom_components.pawsync.update.dr.async_get", return_value=dev_reg), \
             patch("custom_components.pawsync.update.async_ensure_firmware_binary", new_callable=AsyncMock, return_value=dummy_fw), \
             patch("custom_components.pawsync.update.patch_raw_esp32_credentials", return_value=b"\xe9" + (b"\x00" * 1000)) as mock_patch, \
             patch("custom_components.pawsync.update.async_flash_esphome_ota", new_callable=AsyncMock, return_value=True) as mock_flash, \
             patch("custom_components.pawsync.update.async_write_feeder_secrets", new_callable=AsyncMock) as mock_write_sec:

            entity = PawSyncFirmwareUpdateEntity(hass, pawsync_entry)
            await entity.async_install()

            # Verify that update INHERITED the key from active ESPHome entry!
            assert mock_patch.call_args.kwargs["noise_psk"] == "ActiveESPHomeKey123="
            # Verify secrets were written to secrets.yaml
            assert mock_write_sec.called
            assert mock_write_sec.call_args.kwargs["secrets_dict"]["noise_psk"] == "ActiveESPHomeKey123="
    finally:
        if os.path.exists(dummy_fw):
            os.remove(dummy_fw)


@pytest.mark.asyncio
async def test_update_auto_syncs_new_key_to_esphome_entry():
    """Test update pushes updated key to ESPHome entry and reloads if key changed."""
    hass = MagicMock()
    hass.config.config_dir = "/tmp"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    hass.config_entries.async_reload = AsyncMock()

    # Active ESPHome integration entry with missing/cleared key (e.g. prompt pending)
    esphome_entry = MagicMock()
    esphome_entry.entry_id = "esphome_entry_456"
    esphome_entry.title = "Smart Pet Feeder"
    esphome_entry.unique_id = "aabbccddeeff"
    esphome_entry.data = {
        "host": "192.168.1.50",
        "noise_psk": None,
    }

    def mock_async_entries(domain):
        if domain == "esphome":
            return [esphome_entry]
        return []

    hass.config_entries.async_entries = mock_async_entries

    # PawSync entry with fresh key
    pawsync_entry = MagicMock()
    pawsync_entry.title = "Pawsync Feeder"
    pawsync_entry.data = {
        "feeder_info": {"mac": "AA:BB:CC:DD:EE:FF", "name": "Kitchen Feeder"},
        "host": "192.168.1.50",
        "noise_psk": "NewDesiredKey123=",
        "ota_password": "NewOtaPassword",
    }
    pawsync_entry.options = {}

    dev_reg = MagicMock()
    dev_reg.async_get_device.return_value = MagicMock()

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
        tf.write(b"\x01" + (b"\x00" * 128) + b"\xe9" + (b"\x00" * 1000))
        dummy_fw = tf.name

    try:
        with patch("custom_components.pawsync.update.dr.async_get", return_value=dev_reg), \
             patch("custom_components.pawsync.update.async_ensure_firmware_binary", new_callable=AsyncMock, return_value=dummy_fw), \
             patch("custom_components.pawsync.update.patch_raw_esp32_credentials", return_value=b"\xe9" + (b"\x00" * 1000)), \
             patch("custom_components.pawsync.update.async_flash_esphome_ota", new_callable=AsyncMock, return_value=True), \
             patch("custom_components.pawsync.update.async_write_feeder_secrets", new_callable=AsyncMock):

            entity = PawSyncFirmwareUpdateEntity(hass, pawsync_entry)
            await entity.async_install()

            # Verify that ESPHome entry was updated with the new key and reloaded
            assert hass.config_entries.async_update_entry.called
            assert hass.config_entries.async_reload.called
            assert hass.config_entries.async_reload.call_args[0][0] == "esphome_entry_456"
    finally:
        if os.path.exists(dummy_fw):
            os.remove(dummy_fw)


