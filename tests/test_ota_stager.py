"""Tests for Local OTA Stager and URL Formatting."""

import os
import socket
import struct
import pytest
import aiohttp
from unittest.mock import AsyncMock, patch

from custom_components.pawsync.ota_stager import (
    PawsyncOtaStager,
    format_staging_url,
    get_local_ip,
)


def test_format_staging_url_raw():
    """Verify raw mode leaves URL untouched."""
    url = "http://192.168.1.140:8000/firmware.bin"
    assert format_staging_url(url, mode="raw") == url


def test_format_staging_url_dword():
    """Verify DWORD mode converts IPv4 to decimal DWORD representation."""
    url = "http://192.168.1.140:8000/firmware.bin"
    formatted = format_staging_url(url, mode="dword")
    # 192.168.1.140 in network byte order: 192*2^24 + 168*2^16 + 1*2^8 + 140 = 3232235916
    expected_ip = struct.unpack("!I", socket.inet_aton("192.168.1.140"))[0]
    assert formatted == f"http://{expected_ip}:8000/firmware.bin"


def test_format_staging_url_sslip():
    """Verify sslip mode converts IPv4 to sslip.io FQDN."""
    url = "http://192.168.1.140:8000/firmware.bin"
    formatted = format_staging_url(url, mode="sslip")
    assert formatted == "http://192-168-1-140.sslip.io:8000/firmware.bin"


@pytest.mark.asyncio
async def test_ota_stager_lifecycle(tmp_path):
    """Verify OTA stager can bind, serve a dummy file, and clean up."""
    dummy_fw = tmp_path / "firmware.bin"
    dummy_fw.write_bytes(b"A" * 129 + b"B" * 2048)

    stager = PawsyncOtaStager(firmware_path=str(dummy_fw), port=0)
    try:
        url = await stager.async_start()
        assert stager.is_running is True
        assert stager.sha256 is not None
        assert len(stager.sha256) == 64
        assert f"/firmware_{stager.token}.bin" in url
    finally:
        await stager.async_stop()
        assert stager.is_running is False


@pytest.mark.asyncio
async def test_ota_stager_file_too_small(tmp_path):
    """Verify OTA stager rejects file smaller than 129 bytes."""
    small_fw = tmp_path / "small.bin"
    small_fw.write_bytes(b"TOO_SHORT")

    stager = PawsyncOtaStager(firmware_path=str(small_fw), port=0)
    with pytest.raises(ValueError, match="too small"):
        await stager.async_start()


@pytest.mark.asyncio
async def test_ota_stager_auto_timeout(tmp_path):
    """Verify OTA stager automatically shuts down after idle timeout."""
    import asyncio
    dummy_fw = tmp_path / "firmware.bin"
    dummy_fw.write_bytes(b"A" * 129 + b"B" * 2048)

    stager = PawsyncOtaStager(firmware_path=str(dummy_fw), port=0)
    stager.timeout_sec = 0.05  # Short timeout for test
    url = await stager.async_start()
    assert stager.is_running is True
    # Wait for timeout to trigger
    await asyncio.sleep(0.1)
    assert stager.is_running is False


@pytest.mark.asyncio
async def test_ota_stager_relative_path_tempfile_fallback(tmp_path, monkeypatch):
    """Verify OTA stager uses tempfile when firmware_path has no directory component."""
    from tests.fixtures.synthetic_firmware import create_synthetic_vesync_container

    monkeypatch.chdir(tmp_path)
    dummy_fw = tmp_path / "firmware.bin"
    dummy_fw.write_bytes(create_synthetic_vesync_container())

    # Relative path with no directory component
    stager = PawsyncOtaStager(
        firmware_path="firmware.bin",
        port=0,
        wifi_ssid="TestSSID",
        wifi_password="TestPassword",
    )
    try:
        url = await stager.async_start()
        assert stager.is_running is True
        assert stager.sha256 is not None
    finally:
        await stager.async_stop()


@pytest.mark.asyncio
async def test_ota_stager_untokenized_routes_return_404(tmp_path):
    """Verify legacy untokenized stager routes return 404 Not Found."""
    dummy_fw = tmp_path / "firmware.bin"
    dummy_fw.write_bytes(b"A" * 129 + b"B" * 2048)

    stager = PawsyncOtaStager(firmware_path=str(dummy_fw), port=0)
    try:
        url = await stager.async_start()
        base_url = url.rsplit("/", 1)[0]

        async with aiohttp.ClientSession() as session:
            # Untokenized routes must return 404
            async with session.get(f"{base_url}/firmware.bin") as resp:
                assert resp.status == 404

            async with session.get(f"{base_url}/pawsync_ota_update.bin") as resp:
                assert resp.status == 404
    finally:
        await stager.async_stop()


@pytest.mark.asyncio
async def test_ota_stager_one_shot_rejection(tmp_path):
    """Verify duplicate download requests are rejected with 410 Gone."""
    dummy_fw = tmp_path / "firmware.bin"
    dummy_fw.write_bytes(b"A" * 129 + b"B" * 512)

    stager = PawsyncOtaStager(firmware_path=str(dummy_fw), port=0)
    try:
        url = await stager.async_start()

        async with aiohttp.ClientSession() as session:
            # First request connects and initiates download
            async with session.get(url) as resp1:
                assert resp1.status == 200

            # Second request must be rejected as one-shot link has already been used
            async with session.get(url) as resp2:
                assert resp2.status == 410
    finally:
        await stager.async_stop()


@pytest.mark.asyncio
async def test_ota_stager_customized_file_cleanup(tmp_path):
    """Verify pawsync_ota_customized.bin is guaranteed to be deleted on stager stop."""
    from tests.fixtures.synthetic_firmware import create_synthetic_vesync_container

    dummy_fw = tmp_path / "firmware.bin"
    dummy_fw.write_bytes(create_synthetic_vesync_container())

    stager = PawsyncOtaStager(
        firmware_path=str(dummy_fw),
        port=0,
        wifi_ssid="TestCleanSSID",
        wifi_password="TestCleanPassword",
    )
    url = await stager.async_start()
    assert stager.is_running is True
    assert stager._customized_path is not None
    assert os.path.exists(stager._customized_path) is True

    # Stop stager
    await stager.async_stop()
    assert stager.is_running is False
    # Verify temporary customized binary was deleted
    assert os.path.exists(stager._customized_path or "") is False


@pytest.mark.asyncio
async def test_ota_stager_customizes_noise_psk_and_ota_password(tmp_path):
    """Verify stager patches Wi-Fi, Noise PSK, and OTA password into served image."""
    from custom_components.pawsync.firmware_patcher import (
        SSID_PLACEHOLDER,
        PASS_PLACEHOLDER,
        NOISE_PSK_PLACEHOLDER,
        OTA_PASSWORD_PLACEHOLDER,
        package_vesync_ota_container,
        recalculate_esp32_checksum,
        recalculate_esp32_sha256,
        generate_noise_psk,
        generate_ota_password,
    )

    dummy_fw = tmp_path / "firmware.bin"
    payload = (
        b"INIT_"
        + SSID_PLACEHOLDER
        + b"_MID_"
        + PASS_PLACEHOLDER
        + b"_PSK_"
        + NOISE_PSK_PLACEHOLDER
        + b"_OTA_"
        + OTA_PASSWORD_PLACEHOLDER
        + b"_TAIL"
    )
    seg_header = struct.pack("<II", 0x3FFB0000, len(payload))
    raw = bytearray(24)
    raw[0] = 0xE9
    raw[1] = 1
    raw += seg_header + payload
    raw += bytearray(33)
    recalculate_esp32_checksum(raw)
    recalculate_esp32_sha256(raw)
    dummy_fw.write_bytes(package_vesync_ota_container(bytes(raw)))

    test_psk = generate_noise_psk()
    test_ota = generate_ota_password(16)

    stager = PawsyncOtaStager(
        firmware_path=str(dummy_fw),
        port=0,
        wifi_ssid="PawsyncSSID",
        wifi_password="PawsyncPassword",
        noise_psk=test_psk,
        ota_password=test_ota,
    )
    url = await stager.async_start()
    try:
        assert stager.is_running is True
        assert stager._customized_path is not None
        customized_bytes = open(stager._customized_path, "rb").read()
        assert b"PawsyncSSID" in customized_bytes
        assert b"PawsyncPassword" in customized_bytes
        assert test_psk.encode("ascii") in customized_bytes
        assert test_ota.encode("ascii") in customized_bytes
    finally:
        await stager.async_stop()
