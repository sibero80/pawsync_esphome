"""Firmware Binary Resolver and Downloader for PawSync Pet Feeder.

Provides dynamic on-demand retrieval of the verified VeSync OTA container
(pawsync_ota_update.bin) from the transparent upstream repository
(https://github.com/sibero80/pawsync_ota) with local caching and offline fallback.
"""

from __future__ import annotations

import hashlib
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

# Pinned release digests: maps release tag / version to expected sha256 hex digest
EXPECTED_FIRMWARE_DIGESTS: dict[str, str] = {
    "1.5.0": "d499f27d636d2be95cc078c9b87f2e04d13c8b5074d86f954fdb293fd4730164",
    "1.5.0-beta": "d499f27d636d2be95cc078c9b87f2e04d13c8b5074d86f954fdb293fd4730164",
}


def verify_firmware_digest(content: bytes, expected_digest: str) -> bool:
    """Verify that firmware content matches expected SHA-256 digest."""
    clean_expected = expected_digest.lower().removeprefix("sha256:")
    actual = hashlib.sha256(content).hexdigest().lower()
    return actual == clean_expected


def get_firmware_cache_dir(hass: HomeAssistant) -> str:
    """Return the directory path where firmware containers are cached."""
    config_dir = getattr(hass.config, "config_dir", "/config") or "/config"
    return os.path.join(config_dir, ".storage", "pawsync")


def get_local_firmware_candidates(hass: HomeAssistant) -> list[str]:
    """Return an ordered list of search paths for local firmware binaries."""
    config_dir = getattr(hass.config, "config_dir", "/config") or "/config"
    return [
        os.path.join(config_dir, ".storage", "pawsync", OTA_BINARY_FILENAME),
        os.path.join(config_dir, "pawsync", OTA_BINARY_FILENAME),
        os.path.join(config_dir, OTA_BINARY_FILENAME),
        os.path.join(os.path.dirname(__file__), OTA_BINARY_FILENAME),
    ]


def validate_firmware_container(path: str, require_patchable: bool = False) -> bool:
    """Validate that a firmware file exists, matches the VeSync container structure,
    and optionally contains dynamic Wi-Fi placeholders."""
    if not os.path.exists(path):
        return False
    try:
        size = os.path.getsize(path)
        if size < MIN_CONTAINER_SIZE or size > MAX_CONTAINER_SIZE:
            _LOGGER.debug("Candidate %s size %d out of bounds (%d..%d)", path, size, MIN_CONTAINER_SIZE, MAX_CONTAINER_SIZE)
            return False

        with open(path, "rb") as f:
            content = f.read()

        if not content or content[0] != CONTAINER_MAGIC_BYTE:
            _LOGGER.debug("Candidate %s has invalid header byte (expected 0x01)", path)
            return False

        if require_patchable:
            from .firmware_patcher import can_patch_firmware
            if not can_patch_firmware(content, require_psk=True, require_ota=True):
                _LOGGER.info(
                    "Candidate %s lacks dynamic placeholders; discarding stale cache",
                    path,
                )
                return False

        return True
    except Exception as err:
        _LOGGER.debug("Failed to inspect candidate %s: %s", path, err)
        return False


async def async_ensure_firmware_binary(
    hass: HomeAssistant,
    version: str | None = None,
    session: aiohttp.ClientSession | None = None,
    require_patchable: bool = False,
    expected_digest: str | None = None,
) -> str:
    """Ensure a verified firmware container is available locally.

    Searches local storage paths first. If not present, stale, or invalid, downloads
    the verified binary from the official upstream repository (sibero80/pawsync_ota).
    Enforces optional or pinned SHA-256 digest checks.
    """
    clean_v = version.lstrip("v") if version else None
    pinned_digest = expected_digest or (EXPECTED_FIRMWARE_DIGESTS.get(clean_v) if clean_v else None)

    # 1. Check local candidates
    for candidate in get_local_firmware_candidates(hass):
        if validate_firmware_container(candidate, require_patchable=require_patchable):
            if pinned_digest:
                try:
                    with open(candidate, "rb") as f:
                        cand_content = f.read()
                    if not verify_firmware_digest(cand_content, pinned_digest):
                        _LOGGER.warning("Local candidate %s failed SHA-256 verification", candidate)
                        continue
                except Exception as err:
                    _LOGGER.debug("Could not verify candidate %s hash: %s", candidate, err)
                    continue

            _LOGGER.info("Using local firmware container: %s (%d bytes)", candidate, os.path.getsize(candidate))
            return candidate
        elif os.path.exists(candidate) and require_patchable:
            # Stale candidate without patch placeholders; clean up to avoid reuse
            try:
                os.remove(candidate)
                _LOGGER.info("Removed stale cached firmware: %s", candidate)
            except Exception as err:
                _LOGGER.debug("Could not remove stale candidate %s: %s", candidate, err)

    _LOGGER.info(
        "No valid local %s found. Downloading from upstream repository (%s)...",
        OTA_BINARY_FILENAME,
        DEFAULT_OTA_REPO,
    )

    # 2. Determine download URLs
    urls: list[str] = []
    if version:
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

                # Verify pinned SHA-256 digest
                if pinned_digest and not verify_firmware_digest(content, pinned_digest):
                    _LOGGER.error(
                        "Firmware SHA-256 digest verification failed for %s (actual: %s, expected: %s)",
                        url,
                        hashlib.sha256(content).hexdigest(),
                        pinned_digest,
                    )
                    raise HomeAssistantError("Firmware SHA-256 digest verification failed")

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

        except HomeAssistantError:
            raise
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
