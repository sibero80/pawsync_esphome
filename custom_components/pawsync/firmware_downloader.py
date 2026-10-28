"""Firmware Binary Resolver and Downloader for PawSync Pet Feeder.

Provides dynamic on-demand retrieval of the verified VeSync OTA container
(pawsync_ota_update.bin) from the transparent upstream repository
(https://github.com/sibero80/pawsync_ota) with local caching and offline fallback.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

DEFAULT_OTA_REPO = "sibero80/pawsync_ota"
OTA_BINARY_FILENAME = "pawsync_ota_update.bin"
MIN_CONTAINER_SIZE = 500_000
MAX_CONTAINER_SIZE = 1_310_720  # Partition limit: 0x140000 bytes
CONTAINER_MAGIC_BYTE = 0x01


def get_local_firmware_candidates(hass: HomeAssistant) -> list[str]:
    """Return an ordered list of search paths for local firmware binaries."""
    config_dir = getattr(hass.config, "config_dir", "/config") or "/config"
    return [
        os.path.join(config_dir, ".storage", "pawsync", OTA_BINARY_FILENAME),
        os.path.join(config_dir, "pawsync", OTA_BINARY_FILENAME),
        os.path.join(config_dir, OTA_BINARY_FILENAME),
        os.path.join(os.path.dirname(__file__), OTA_BINARY_FILENAME),
    ]


def validate_firmware_container(path: str) -> bool:
    """Validate that a firmware file exists and matches the VeSync container structure."""
    if not os.path.exists(path):
        return False
    try:
        size = os.path.getsize(path)
        if size < MIN_CONTAINER_SIZE or size > MAX_CONTAINER_SIZE:
            _LOGGER.debug("Candidate %s size %d out of bounds (%d..%d)", path, size, MIN_CONTAINER_SIZE, MAX_CONTAINER_SIZE)
            return False

        with open(path, "rb") as f:
            header = f.read(1)
            if not header or header[0] != CONTAINER_MAGIC_BYTE:
                _LOGGER.debug("Candidate %s has invalid header byte (expected 0x01, got %s)", path, header)
                return False

        return True
    except Exception as err:
        _LOGGER.debug("Failed to inspect candidate %s: %s", path, err)
        return False


async def async_ensure_firmware_binary(
    hass: HomeAssistant,
    version: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> str:
    """Ensure a verified firmware container is available locally.

    Searches local storage paths first. If not present or invalid, downloads
    the verified binary from the official upstream repository (sibero80/pawsync_ota).
    """
    # 1. Check local candidates
    for candidate in get_local_firmware_candidates(hass):
        if validate_firmware_container(candidate):
            _LOGGER.info("Using local firmware container: %s (%d bytes)", candidate, os.path.getsize(candidate))
            return candidate

    _LOGGER.info(
        "No valid local %s found. Downloading from upstream repository (%s)...",
        OTA_BINARY_FILENAME,
        DEFAULT_OTA_REPO,
    )

    # 2. Determine download URLs
    urls: list[str] = []
    if version:
        clean_v = version.lstrip("v")
        urls.append(f"https://github.com/{DEFAULT_OTA_REPO}/releases/download/v{clean_v}/{OTA_BINARY_FILENAME}")
        urls.append(f"https://github.com/{DEFAULT_OTA_REPO}/releases/download/{clean_v}/{OTA_BINARY_FILENAME}")
    urls.append(f"https://github.com/{DEFAULT_OTA_REPO}/releases/latest/download/{OTA_BINARY_FILENAME}")

    client_session = session or async_get_clientsession(hass)
    config_dir = getattr(hass.config, "config_dir", "/config") or "/config"
    target_dir = os.path.join(config_dir, ".storage", "pawsync")

    def _prepare_target_dir() -> str:
        os.makedirs(target_dir, exist_ok=True)
        return target_dir

    await hass.async_add_executor_job(_prepare_target_dir)
    target_file = os.path.join(target_dir, OTA_BINARY_FILENAME)

    last_error: Exception | None = None
    for url in urls:
        _LOGGER.debug("Attempting firmware download from: %s", url)
        try:
            async with client_session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    _LOGGER.debug("HTTP %d from %s", resp.status, url)
                    continue

                content = await resp.read()

                # Validate downloaded bytes
                if len(content) < MIN_CONTAINER_SIZE or len(content) > MAX_CONTAINER_SIZE:
                    _LOGGER.warning(
                        "Downloaded binary from %s has invalid size (%d bytes; expected %d..%d)",
                        url,
                        len(content),
                        MIN_CONTAINER_SIZE,
                        MAX_CONTAINER_SIZE,
                    )
                    continue

                if content[0] != CONTAINER_MAGIC_BYTE:
                    _LOGGER.warning(
                        "Downloaded binary from %s does not match VeSync container format (byte 0 != 0x01)",
                        url,
                    )
                    continue

                # Write to disk atomically
                def _write_file():
                    temp_fd, temp_path = tempfile.mkstemp(dir=target_dir, prefix="pawsync_fw_")
                    try:
                        with os.fdopen(temp_fd, "wb") as f:
                            f.write(content)
                        shutil.move(temp_path, target_file)
                    except Exception:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        raise

                await hass.async_add_executor_job(_write_file)
                _LOGGER.info(
                    "Successfully downloaded and verified %s (%d bytes) from %s -> %s",
                    OTA_BINARY_FILENAME,
                    len(content),
                    url,
                    target_file,
                )
                return target_file

        except Exception as err:
            _LOGGER.debug("Download failed from %s: %s", url, err)
            last_error = err

    error_msg = (
        f"Could not locate or download '{OTA_BINARY_FILENAME}' from https://github.com/{DEFAULT_OTA_REPO}/releases. "
        f"Please verify internet connectivity or manually copy '{OTA_BINARY_FILENAME}' into '{config_dir}'."
    )
    if last_error:
        _LOGGER.error("%s (Last error: %s)", error_msg, last_error)
    raise HomeAssistantError(error_msg)
