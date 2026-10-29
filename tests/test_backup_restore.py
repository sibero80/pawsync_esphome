"""Unit and integration tests for zero-teardown factory backup and 1-click restore."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import struct
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pawsync.backup_manager import (
    FAC_DATA_SIZE,
    async_check_device_backup_status,
    async_harvest_factory_backup,
    get_backup_dir,
    get_backup_paths,
    has_valid_local_backup,
    sanitize_mac,
    strip_trailing_padding,
    validate_esp_idf_image,
    validate_nvs_calibration,
)
from custom_components.pawsync.config_flow import PawsyncOptionsFlowHandler
from custom_components.pawsync.const import (
    BACKUP_STATUS_BACKED_UP,
    BACKUP_STATUS_PENDING,
    BACKUP_STATUS_SLOT_OVERWRITTEN,
    BACKUP_STATUS_UNAVAILABLE,
    DOMAIN,
)
from custom_components.pawsync.sensor import (
    SLOT_STATE_ESPHOME_OVERWRITTEN,
    SLOT_STATE_STOCK_PRESERVED,
    PawSyncAlternateSlotSensor,
    PawSyncStockBackupStatusSensor,
)
from custom_components.pawsync.services import async_setup_services
from custom_components.pawsync.update import PawSyncFirmwareUpdateEntity


def create_mock_esp_idf_binary(
    project: str = "pawsync_stock",
    version: str = "v1.0.29",
    magic_byte: int = 0xE9,
    include_desc_magic: bool = True,
    pad_bytes: int = 0,
) -> bytes:
    """Helper to synthesize a valid ESP-IDF application binary header and esp_app_desc."""
    header = bytearray(32)
    header[0] = magic_byte
    header[1] = 4  # 4 segments
    header[2] = 0x02  # flash mode
    header[3] = 0x20  # 4MB flash

    # esp_app_desc_t at offset 32
    desc = bytearray(144)
    if include_desc_magic:
        # Magic word 0xABCD5432 in little endian
        desc[0:4] = struct.pack("<I", 0xABCD5432)
    desc[4:8] = struct.pack("<I", 0)  # secure_version
    # version (32 bytes)
    ver_bytes = version.encode("utf-8")[:31]
    desc[16 : 16 + len(ver_bytes)] = ver_bytes
    # project_name (32 bytes)
    proj_bytes = project.encode("utf-8")[:31]
    desc[48 : 48 + len(proj_bytes)] = proj_bytes
    # time & date
    desc[80:96] = b"12:00:00\x00" + b"\x00" * 7
    desc[96:112] = b"Oct 29 2026\x00" + b"\x00" * 4
    # idf_ver
    desc[112:144] = b"v5.1.2\x00" + b"\x00" * 25

    payload = header + desc + (b"\xAA" * 100)
    if pad_bytes > 0:
        payload += b"\xff" * pad_bytes
    return bytes(payload)


def create_mock_fac_data(include_key: bool = True, size: int = FAC_DATA_SIZE) -> bytes:
    """Helper to synthesize a mock fac_data NVS calibration partition."""
    data = bytearray(size)
    # NVS page header signature (0xfeffffff00000000...)
    data[0:4] = b"\xfe\xff\xff\xff"
    if include_key:
        # embed prd_cfg_data key
        data[64 : 64 + len(b"prd_cfg_data")] = b"prd_cfg_data"
    return bytes(data)


# -----------------------------------------------------------------------------
# Unit Tests: Padding Stripping & Image Validation
# -----------------------------------------------------------------------------

def test_strip_trailing_padding_exact():
    """Verify 0xFF flash padding is stripped cleanly from raw partition data."""
    raw = b"binary_data_here\xff\xff\xff\xff\xff"
    assert strip_trailing_padding(raw) == b"binary_data_here"
    assert strip_trailing_padding(b"") == b""
    assert strip_trailing_padding(b"already_clean") == b"already_clean"


def test_strip_trailing_padding_partition_scale():
    """Simulate 1,310,720-byte partition stripped to authentic 978,688 bytes."""
    clean_size = 978688
    total_slot_size = 1310720
    simulated_partition = b"\x55" * clean_size + b"\xff" * (total_slot_size - clean_size)

    trimmed = strip_trailing_padding(simulated_partition)
    assert len(trimmed) == clean_size
    assert trimmed == b"\x55" * clean_size


def test_validate_esp_idf_image_success():
    """Verify validation passes for genuine ESP-IDF image binary."""
    image = create_mock_esp_idf_binary(project="vesync_feeder", version="v1.0.29")
    valid, err, meta = validate_esp_idf_image(image)
    assert valid is True
    assert "Valid ESP-IDF image" in err
    assert meta["project"] == "vesync_feeder"
    assert meta["version"] == "v1.0.29"
    assert meta["segment_count"] == 4


def test_validate_esp_idf_image_failures():
    """Verify failure modes for corrupted or non-ESP-IDF binaries."""
    # Too small
    valid, err, _ = validate_esp_idf_image(b"tiny")
    assert valid is False
    assert "too small" in err

    # Wrong magic byte
    bad_magic = create_mock_esp_idf_binary(magic_byte=0x42)
    valid, err, _ = validate_esp_idf_image(bad_magic)
    assert valid is False
    assert "magic byte: 0x42" in err

    # Missing esp_app_desc magic
    no_desc = create_mock_esp_idf_binary(include_desc_magic=False)
    valid, err, _ = validate_esp_idf_image(no_desc)
    assert valid is False
    assert "esp_app_desc" in err


def test_validate_nvs_calibration_success():
    """Verify validation of factory NVS calibration partition."""
    cal_data = create_mock_fac_data()
    valid, err = validate_nvs_calibration(cal_data)
    assert valid is True
    assert "Valid factory calibration" in err


def test_validate_nvs_calibration_failures():
    """Verify validation failures for corrupted calibration partitions."""
    # Wrong size
    valid, err = validate_nvs_calibration(b"\xfe\xff\xff\xff" + b"\x00" * 100)
    assert valid is False
    assert "Invalid calibration size" in err

    # Bad header
    bad_header = b"\xaa\xaa\xaa\xaa" + b"\x00" * (FAC_DATA_SIZE - 4)
    valid, err = validate_nvs_calibration(bad_header)
    assert valid is False
    assert "Invalid NVS page header" in err

    # Missing key
    no_key = create_mock_fac_data(include_key=False)
    valid, err = validate_nvs_calibration(no_key)
    assert valid is False
    assert "prd_cfg_data" in err


def test_sanitize_mac():
    """Verify MAC sanitization formats string for safe filesystem usage."""
    assert sanitize_mac("AA:BB:CC:11:22:33") == "aabbcc112233"
    assert sanitize_mac("aa-bb-cc-11-22-33") == "aabbcc112233"
    assert sanitize_mac("../../root/bad") == "bad"
    assert sanitize_mac("") == "unknown"


# -----------------------------------------------------------------------------
# Unit Tests: Filesystem Persistence & Permissions
# -----------------------------------------------------------------------------

def test_backup_persistence_permissions(tmp_path):
    """Assert backups write to /config/pawsync_backups/ with POSIX 0600 permissions."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)

    stock_path, cal_path = get_backup_paths(mock_hass, "AA:BB:CC:DD:EE:FF")
    assert stock_path.name == "stock_aabbccddeeff.bin"
    assert cal_path.name == "cal_aabbccddeeff.bin"

    # Simulate writing backup files
    stock_bin = create_mock_esp_idf_binary()
    cal_bin = create_mock_fac_data()
    stock_path.write_bytes(stock_bin)
    os.chmod(stock_path, 0o600)
    cal_path.write_bytes(cal_bin)
    os.chmod(cal_path, 0o600)

    assert (stock_path.stat().st_mode & 0o777) == 0o600
    assert (cal_path.stat().st_mode & 0o777) == 0o600
    assert has_valid_local_backup(mock_hass, "AA:BB:CC:DD:EE:FF") is True


# -----------------------------------------------------------------------------
# Integration Tests: End-to-End Backup Harvesting
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_harvest_factory_backup_success(tmp_path):
    """Test full automated harvest pipeline across HTTP streaming mock."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)

    raw_stock = create_mock_esp_idf_binary(project="vesync_feeder", version="v1.0.29", pad_bytes=512)
    raw_cal = create_mock_fac_data()

    # Mock responses for /export_status, /export_stock_bin, /export_calibration
    mock_session = MagicMock()

    class MockResp:
        def __init__(self, data=None, json_data=None, status=200):
            self._data = data
            self._json_data = json_data
            self.status = status

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def read(self):
            return self._data

        async def json(self):
            return self._json_data

    def get_url_mock(url, **kwargs):
        if "export_status" in str(url):
            return MockResp(json_data={"stock_intact": True, "slot": "ota_1", "version": "v1.0.29"})
        if "export_stock_bin" in str(url):
            return MockResp(data=raw_stock)
        if "export_calibration" in str(url):
            return MockResp(data=raw_cal)
        return MockResp(status=404)

    mock_session.get.side_effect = get_url_mock

    result = await async_harvest_factory_backup(
        mock_hass,
        host="192.168.1.45",
        mac="AA:BB:CC:DD:EE:FF",
        session=mock_session,
    )

    assert result["status"] == BACKUP_STATUS_BACKED_UP
    stock_path, cal_path = get_backup_paths(mock_hass, "AA:BB:CC:DD:EE:FF")
    assert stock_path.exists()
    assert cal_path.exists()
    assert (stock_path.stat().st_mode & 0o777) == 0o600
    assert (cal_path.stat().st_mode & 0o777) == 0o600
    assert result["metadata"]["version"] == "v1.0.29"


@pytest.mark.asyncio
async def test_async_harvest_slot_overwritten(tmp_path):
    """Verify harvester detects and halts if stock partition was already overwritten."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)

    mock_session = MagicMock()

    class MockResp:
        def __init__(self, json_data):
            self._json_data = json_data
            self.status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def json(self):
            return self._json_data

    mock_session.get.return_value = MockResp({"stock_intact": False, "slot": "ota_1"})

    result = await async_harvest_factory_backup(
        mock_hass,
        host="192.168.1.45",
        mac="AA:BB:CC:DD:EE:FF",
        session=mock_session,
    )

    assert result["status"] == BACKUP_STATUS_SLOT_OVERWRITTEN
    stock_path, _ = get_backup_paths(mock_hass, "AA:BB:CC:DD:EE:FF")
    assert not stock_path.exists()


# -----------------------------------------------------------------------------
# Diagnostic Entity Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_diagnostic_sensors_lifecycle(tmp_path):
    """Test state reporting for backup status and alternate slot sensors."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    entry = MagicMock()
    entry.data = {
        "feeder_info": {"mac": "AA:BB:CC:DD:EE:FF", "name": "Feeder", "ip": "192.168.1.45"},
    }
    entry.options = {}

    status_sensor = PawSyncStockBackupStatusSensor(mock_hass, entry)
    slot_sensor = PawSyncAlternateSlotSensor(mock_hass, entry)

    assert status_sensor.unique_id == "AA:BB:CC:DD:EE:FF_stock_backup_status"
    assert slot_sensor.unique_id == "AA:BB:CC:DD:EE:FF_alternate_slot_state"

    # 1. Initially pending when no local backup exists and device unavailable
    with patch("custom_components.pawsync.sensor.async_check_device_backup_status", return_value={"error": "timeout"}):
        await status_sensor.async_update()
        assert status_sensor.native_value == BACKUP_STATUS_UNAVAILABLE

        await slot_sensor.async_update()
        assert slot_sensor.native_value == "Unavailable"

    # 2. Device reports stock intact
    with patch("custom_components.pawsync.sensor.async_check_device_backup_status", return_value={"stock_intact": True, "slot": "ota_1", "version": "v1.0.29"}):
        await status_sensor.async_update()
        assert status_sensor.native_value == BACKUP_STATUS_PENDING

        await slot_sensor.async_update()
        assert slot_sensor.native_value == SLOT_STATE_STOCK_PRESERVED

    # 3. Valid backup created locally
    stock_path, cal_path = get_backup_paths(mock_hass, "AA:BB:CC:DD:EE:FF")
    stock_path.write_bytes(create_mock_esp_idf_binary())
    cal_path.write_bytes(create_mock_fac_data())

    await status_sensor.async_update()
    assert status_sensor.native_value == BACKUP_STATUS_BACKED_UP


# -----------------------------------------------------------------------------
# 1-Click Restore Service Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restore_stock_service_guards(tmp_path):
    """Test safety guards on service pawsync.restore_stock_firmware."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    mock_hass.services.has_service.return_value = False

    registered_services = {}

    def mock_register(domain, service, handler, schema=None):
        registered_services[service] = handler

    mock_hass.services.async_register.side_effect = mock_register

    await async_setup_services(mock_hass)
    assert "restore_stock_firmware" in registered_services

    restore_handler = registered_services["restore_stock_firmware"]

    # 1. Unconfirmed call must raise HomeAssistantError
    call_unconfirmed = MagicMock()
    call_unconfirmed.data = {"confirm": False}
    with pytest.raises(Exception) as excinfo:
        await restore_handler(call_unconfirmed)
    assert "Confirmation required" in str(excinfo.value)

    # 2. Missing backup file must raise error
    call_confirmed = MagicMock()
    call_confirmed.data = {"confirm": True, "host": "192.168.1.45", "mac": "AA:BB:CC:DD:EE:FF"}
    with pytest.raises(Exception) as excinfo:
        await restore_handler(call_confirmed)
    assert "No stock firmware backup file found" in str(excinfo.value)

    # 3. Successful OTA restore
    stock_path, cal_path = get_backup_paths(mock_hass, "AA:BB:CC:DD:EE:FF")
    stock_path.write_bytes(create_mock_esp_idf_binary(project="vesync_feeder", version="v1.0.29"))

    with patch("custom_components.pawsync.services.async_flash_esphome_ota", return_value=True) as mock_flash:
        with patch("asyncio.open_connection") as mock_conn:
            mock_writer = MagicMock()
            mock_writer.wait_closed = AsyncMock()
            mock_conn.return_value = (AsyncMock(), mock_writer)

            await restore_handler(call_confirmed)
            assert mock_flash.called
            assert mock_flash.call_args[1]["host"] == "192.168.1.45"


# -----------------------------------------------------------------------------
# Options Flow Manual File Import Tests (FIND-07)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_options_flow_manual_import_success(tmp_path):
    """Test manual stock binary import via OptionsFlow saves to storage with 0600."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)
    mock_hass.config.units.is_metric = True
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    config_entry = MagicMock()
    config_entry.data = {"feeder_info": {"mac": "AA:BB:CC:11:22:33"}}
    config_entry.options = {}

    # Create valid mock image file
    sample_bin = tmp_path / "sample_stock.bin"
    sample_bin.write_bytes(create_mock_esp_idf_binary(project="vesync_feeder", version="v1.0.29"))

    handler = PawsyncOptionsFlowHandler(config_entry)
    handler.hass = mock_hass

    result = await handler.async_step_init(user_input={"stock_backup_file_path": str(sample_bin)})
    assert result["type"] == "create_entry"

    stock_path, _ = get_backup_paths(mock_hass, "AA:BB:CC:11:22:33")
    assert stock_path.is_file()
    assert (stock_path.stat().st_mode & 0o777) == 0o600


@pytest.mark.asyncio
async def test_options_flow_manual_import_file_not_found(tmp_path):
    """Test manual import with non-existent file returns validation error."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)
    mock_hass.config.units.is_metric = True

    config_entry = MagicMock()
    config_entry.data = {"feeder_info": {"mac": "AA:BB:CC:11:22:33"}}
    config_entry.options = {}

    handler = PawsyncOptionsFlowHandler(config_entry)
    handler.hass = mock_hass

    result = await handler.async_step_init(user_input={"stock_backup_file_path": "/path/does/not/exist.bin"})
    assert result["type"] == "form"
    assert result["errors"]["stock_backup_file_path"] == "file_not_found"


@pytest.mark.asyncio
async def test_options_flow_manual_import_invalid_image(tmp_path):
    """Test manual import with corrupted binary returns validation error."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)
    mock_hass.config.units.is_metric = True
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    config_entry = MagicMock()
    config_entry.data = {"feeder_info": {"mac": "AA:BB:CC:11:22:33"}}
    config_entry.options = {}

    corrupted_file = tmp_path / "corrupted.bin"
    corrupted_file.write_bytes(b"not an esp idf image header")

    handler = PawsyncOptionsFlowHandler(config_entry)
    handler.hass = mock_hass

    result = await handler.async_step_init(user_input={"stock_backup_file_path": str(corrupted_file)})
    assert result["type"] == "form"
    assert result["errors"]["stock_backup_file_path"] == "invalid_esp_image"


# -----------------------------------------------------------------------------
# Disambiguation & Overwrite Interlock Tests (FIND-01, FIND-03, FIND-05)
# -----------------------------------------------------------------------------

def test_strip_trailing_padding_preserves_sha256_ending_in_ff():
    """Verify segment table sizing preserves authentic SHA-256 hash bytes ending in 0xFF (FIND-01)."""
    # 24-byte header
    hdr = bytearray(24)
    hdr[0] = 0xE9
    hdr[1] = 1  # 1 segment
    hdr[23] = 1  # hash_appended = True

    seg_data = b"segment_payload_esp32_c3_test_binary_content" * 4
    seg_hdr = struct.pack("<II", 0x10000, len(seg_data))

    payload = hdr + seg_hdr + seg_data
    payload += b"\xef"  # 1-byte checksum
    pad_len = (16 - (len(payload) % 16)) % 16
    payload += b"\x00" * pad_len

    # SHA-256 digest ending in 0xFF 0xFF
    sha_hash = b"\x42" * 30 + b"\xff\xff"
    raw_image = payload + sha_hash

    # Simulate SPI flash erase tail padding
    padded_flash = raw_image + b"\xff" * 2048

    trimmed = strip_trailing_padding(padded_flash)
    assert len(trimmed) == len(raw_image)
    assert trimmed == raw_image
    assert trimmed.endswith(b"\xff\xff")


@pytest.mark.asyncio
async def test_restore_stock_multi_feeder_disambiguation(tmp_path):
    """Test restore service raises error if multiple feeders exist and target is omitted (FIND-05)."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)
    mock_hass.services.has_service.return_value = False

    # Simulate 2 registered feeders
    mock_hass.data = {
        DOMAIN: {
            "entry_1": {"feeder_info": {"ip": "192.168.1.45", "mac": "AA:BB:CC:11:22:33"}},
            "entry_2": {"feeder_info": {"ip": "192.168.1.46", "mac": "AA:BB:CC:44:55:66"}},
        }
    }

    registered_services = {}

    def mock_register(domain, service, handler, schema=None):
        registered_services[service] = handler

    mock_hass.services.async_register.side_effect = mock_register

    await async_setup_services(mock_hass)
    restore_handler = registered_services["restore_stock_firmware"]

    call = MagicMock()
    call.data = {"confirm": True}  # Neither host nor mac provided

    with pytest.raises(Exception) as excinfo:
        await restore_handler(call)
    assert "Multiple PawSync feeders found" in str(excinfo.value)


@pytest.mark.asyncio
async def test_update_platform_overwrite_protection_blocked(tmp_path):
    """Test update platform blocks OTA flash when stock is intact, overwrite switch is OFF, and no backup exists (FIND-03)."""
    mock_hass = MagicMock()
    mock_hass.config.path.side_effect = lambda rel: str(tmp_path / rel)
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    entry = MagicMock()
    entry.data = {
        "feeder_info": {"ip": "192.168.1.45", "mac": "AA:BB:CC:11:22:33", "name": "Feeder"},
        "noise_psk": "2M4yBDYqWbBDSl3PIkccw2IkCUj5WIySqP8JHYVG7Mc=",
    }
    entry.options = {}

    entity = PawSyncFirmwareUpdateEntity(mock_hass, entry)
    entity._host = "192.168.1.45"
    entity._mac = "AA:BB:CC:11:22:33"

    mock_session = MagicMock()

    class MockResp:
        def __init__(self, json_data):
            self._json_data = json_data
            self.status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def json(self):
            return self._json_data

    # Feeder reports stock intact, allow_overwrite: False
    mock_session.get.return_value = MockResp({"stock_intact": True, "allow_overwrite": False})

    with patch("custom_components.pawsync.update.async_get_clientsession", return_value=mock_session):
        with patch("custom_components.pawsync.update.has_valid_local_backup", return_value=False):
            with pytest.raises(Exception) as excinfo:
                await entity.async_install()
            assert "Firmware update blocked" in str(excinfo.value)
            assert "Allow Overwriting Stock Slot" in str(excinfo.value)

