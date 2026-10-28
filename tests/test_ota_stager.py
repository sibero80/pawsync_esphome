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
