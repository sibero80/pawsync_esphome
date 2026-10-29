"""Factory Firmware and Calibration Backup Manager for PawSync Feeder."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import re
import struct
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    BACKUP_HTTP_PORT,
    BACKUP_STATUS_BACKED_UP,
    BACKUP_STATUS_PENDING,
    BACKUP_STATUS_SLOT_OVERWRITTEN,
    BACKUP_STATUS_UNAVAILABLE,
    DEFAULT_BACKUP_DIR,
)

_LOGGER = logging.getLogger(__name__)

ESP_IMAGE_HEADER_MAGIC = 0xE9
ESP_APP_DESC_MAGIC_WORD = 0xABCD5432
FAC_DATA_SIZE = 8192
CHUNK_DOWNLOAD_SIZE = 8192


def sanitize_mac(mac: str) -> str:
    """Normalize MAC address for safe filesystem path representation."""
    cleaned = re.sub(r"[^a-fA-F0-9]", "", mac or "").lower()
    if not cleaned:
        return "unknown"
    return cleaned


def strip_trailing_padding(raw_data: bytes) -> bytes:
    """Extract exact ESP-IDF image binary or strip trailing 0xFF flash erase padding.

    First attempts exact segment table sizing to prevent truncating genuine
    SHA-256 hash bytes ending in 0xFF. Falls back to rstrip(b'\\xff').
    """
    if not raw_data:
        return b""

    # Attempt exact ESP-IDF segment table sizing
    if len(raw_data) >= 24 and raw_data[0] == ESP_IMAGE_HEADER_MAGIC:
        segment_count = raw_data[1]
        hash_appended = raw_data[23]
        offset = 24
        try:
            for _ in range(segment_count):
                _, data_len = struct.unpack("<II", raw_data[offset : offset + 8])
                offset += 8 + data_len
            offset += 1  # 8-bit checksum byte
            offset = (offset + 15) & ~15  # 16-byte alignment
            if hash_appended:
                offset += 32  # Appended SHA-256 digest
            if 0 < offset <= len(raw_data):
                return raw_data[:offset]
        except Exception as err:
            _LOGGER.debug("Segment table sizing fallback to rstrip: %s", err)

    return raw_data.rstrip(b"\xff")


def validate_esp_idf_image(data: bytes) -> tuple[bool, str, dict[str, Any]]:
    """Validate that raw bytes represent a valid ESP-IDF application binary.

    Checks:
    1. Minimum length (>= 256 bytes)
    2. Magic byte (0xE9)
    3. esp_app_desc magic word (0xABCD5432)
    4. Extracts project name, version, and compile date
    """
    if not data or len(data) < 256:
        return False, f"Image payload too small ({len(data) if data else 0} bytes)", {}

    if data[0] != ESP_IMAGE_HEADER_MAGIC:
        return False, f"Invalid ESP image magic byte: 0x{data[0]:02X} (expected 0xE9)", {}

    segment_count = data[1]

    # Search for esp_app_desc magic word 0xABCD5432 in first 512 bytes
    idx = data[:512].find(b"\x32\x54\xcd\xab")
    if idx == -1:
        return False, "esp_app_desc structure magic word (0xABCD5432) not found", {}

    try:
        desc = data[idx : idx + 144]
        version = desc[16:48].split(b"\x00")[0].decode("utf-8", "replace").strip()
        project = desc[48:80].split(b"\x00")[0].decode("utf-8", "replace").strip()
        time_str = desc[80:96].split(b"\x00")[0].decode("utf-8", "replace").strip()
        date_str = desc[96:112].split(b"\x00")[0].decode("utf-8", "replace").strip()
        idf_ver = desc[112:144].split(b"\x00")[0].decode("utf-8", "replace").strip()
    except Exception as err:
        return False, f"Failed parsing esp_app_desc: {err}", {}

    metadata = {
        "project": project,
        "version": version,
        "compile_date": f"{date_str} {time_str}".strip(),
        "idf_version": idf_ver,
        "segment_count": segment_count,
        "size": len(data),
    }

    return True, "Valid ESP-IDF image", metadata


def validate_nvs_calibration(data: bytes) -> tuple[bool, str]:
    """Validate that raw bytes represent the fac_data NVS calibration partition."""
    if not data or len(data) != FAC_DATA_SIZE:
        return False, f"Invalid calibration size: {len(data) if data else 0} bytes (expected {FAC_DATA_SIZE})"

    if not data.startswith(b"\xfe\xff\xff\xff"):
        return False, "Invalid NVS page header signature"

    if b"prd_cfg_data" not in data:
        return False, "Required calibration key 'prd_cfg_data' not found in partition"

    return True, "Valid factory calibration NVS partition"


def get_backup_dir(hass: HomeAssistant) -> Path:
    """Return local backup directory path, ensuring directory exists with secure permissions."""
    backup_dir = Path(hass.config.path(DEFAULT_BACKUP_DIR))
    if not backup_dir.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(backup_dir, 0o700)
        except OSError as err:
            _LOGGER.debug("Could not set 0700 permissions on backup dir %s: %s", backup_dir, err)
    return backup_dir


def get_backup_paths(hass: HomeAssistant, mac: str) -> tuple[Path, Path]:
    """Return (stock_binary_path, calibration_path) for the given MAC address."""
    clean_mac = sanitize_mac(mac)
    backup_dir = get_backup_dir(hass)
    stock_path = backup_dir / f"stock_{clean_mac}.bin"
    cal_path = backup_dir / f"cal_{clean_mac}.bin"
    return stock_path, cal_path


def has_valid_local_backup(hass: HomeAssistant, mac: str) -> bool:
    """Check if valid local backup files already exist on disk for this device."""
    stock_path, cal_path = get_backup_paths(hass, mac)
    if not stock_path.is_file() or not cal_path.is_file():
        return False

    try:
        stock_data = stock_path.read_bytes()
        valid_stock, _, _ = validate_esp_idf_image(stock_data)
        cal_data = cal_path.read_bytes()
        valid_cal, _ = validate_nvs_calibration(cal_data)
        return valid_stock and valid_cal
    except Exception as err:
        _LOGGER.warning("Error inspecting local backup files: %s", err)
        return False


async def async_check_device_backup_status(
    host: str,
    session: aiohttp.ClientSession,
    port: int = BACKUP_HTTP_PORT,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """Query feeder /export_status endpoint for partition and stock integrity telemetry."""
    url = f"http://{host}:{port}/export_status"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status == 200:
                return await resp.json()
            _LOGGER.debug("Device status check returned HTTP %d", resp.status)
            return {"error": f"HTTP {resp.status}"}
    except Exception as err:
        _LOGGER.debug("Could not reach backup status endpoint on %s:%d: %s", host, port, err)
        return {"error": str(err)}


async def async_harvest_factory_backup(
    hass: HomeAssistant,
    host: str,
    mac: str,
    session: aiohttp.ClientSession | None = None,
    port: int = BACKUP_HTTP_PORT,
    force: bool = False,
) -> dict[str, Any]:
    """Extract, sanitize, validate, and store factory firmware and calibration from feeder."""
    stock_path, cal_path = get_backup_paths(hass, mac)

    if not force and has_valid_local_backup(hass, mac):
        _LOGGER.info("Valid factory backup already exists locally for MAC %s", mac)
        return {"status": BACKUP_STATUS_BACKED_UP, "source": "local_cache"}

    http_session = session or async_get_clientsession(hass)

    # 1. Probe status endpoint
    status = await async_check_device_backup_status(host, http_session, port)
    if "error" in status:
        return {"status": BACKUP_STATUS_UNAVAILABLE, "reason": status["error"]}

    if not status.get("stock_intact"):
        _LOGGER.warning(
            "Feeder at %s reports stock partition is already overwritten by ESPHome (slot: %s)",
            host,
            status.get("slot"),
        )
        return {"status": BACKUP_STATUS_SLOT_OVERWRITTEN, "slot": status.get("slot")}

    # 2. Download and strip raw stock partition
    stock_url = f"http://{host}:{port}/export_stock_bin"
    _LOGGER.info("Downloading raw stock partition from %s...", stock_url)
    try:
        async with http_session.get(stock_url, timeout=aiohttp.ClientTimeout(total=30.0)) as resp:
            if resp.status != 200:
                return {"status": "error", "reason": f"HTTP {resp.status} on stock download"}
            raw_stock_data = await resp.read()
    except Exception as err:
        _LOGGER.error("Failed downloading stock partition from %s: %s", stock_url, err)
        return {"status": "error", "reason": f"Download failed: {err}"}

    trimmed_stock = strip_trailing_padding(raw_stock_data)
    valid_stock, stock_err, meta = validate_esp_idf_image(trimmed_stock)
    if not valid_stock:
        _LOGGER.error("Harvested stock image failed validation: %s", stock_err)
        return {"status": "validation_failed", "reason": stock_err}

    # 3. Download and validate factory calibration
    cal_url = f"http://{host}:{port}/export_calibration"
    _LOGGER.info("Downloading factory calibration from %s...", cal_url)
    try:
        async with http_session.get(cal_url, timeout=aiohttp.ClientTimeout(total=10.0)) as resp:
            if resp.status != 200:
                return {"status": "error", "reason": f"HTTP {resp.status} on calibration download"}
            raw_cal_data = await resp.read()
    except Exception as err:
        _LOGGER.error("Failed downloading calibration from %s: %s", cal_url, err)
        return {"status": "error", "reason": f"Calibration download failed: {err}"}

    valid_cal, cal_err = validate_nvs_calibration(raw_cal_data)
    if not valid_cal:
        _LOGGER.error("Harvested calibration failed validation: %s", cal_err)
        return {"status": "validation_failed", "reason": cal_err}

    # 4. Save files with POSIX 0600 permissions
    try:
        stock_path.write_bytes(trimmed_stock)
        os.chmod(stock_path, 0o600)
        cal_path.write_bytes(raw_cal_data)
        os.chmod(cal_path, 0o600)
    except OSError as err:
        _LOGGER.error("Failed saving backup files to disk: %s", err)
        return {"status": "io_error", "reason": str(err)}

    _LOGGER.info(
        "Successfully backed up stock firmware (%d bytes, version: '%s') and calibration (%d bytes) to %s",
        len(trimmed_stock),
        meta.get("version"),
        len(raw_cal_data),
        stock_path.parent,
    )

    return {
        "status": BACKUP_STATUS_BACKED_UP,
        "stock_path": str(stock_path),
        "cal_path": str(cal_path),
        "stock_size": len(trimmed_stock),
        "cal_size": len(raw_cal_data),
        "metadata": meta,
    }


async def async_ensure_factory_backup(
    hass: HomeAssistant,
    host: str,
    mac: str,
    port: int = BACKUP_HTTP_PORT,
) -> dict[str, Any]:
    """Background helper to harvest factory backup if not already present."""
    try:
        return await async_harvest_factory_backup(hass, host, mac, port=port)
    except Exception as err:
        _LOGGER.warning("Unexpected error during automated factory backup for %s: %s", host, err)
        return {"status": "error", "reason": str(err)}
