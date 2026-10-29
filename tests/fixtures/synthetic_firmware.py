"""Synthetic ESP32 and VeSync container firmware generators for in-memory CI testing."""

from __future__ import annotations

import struct
from custom_components.pawsync.firmware_patcher import (
    NOISE_PSK_PLACEHOLDER,
    OTA_PASSWORD_PLACEHOLDER,
    PASS_PLACEHOLDER,
    SSID_PLACEHOLDER,
    package_vesync_ota_container,
    recalculate_esp32_checksum,
    recalculate_esp32_sha256,
)


def create_synthetic_esp32_binary(
    include_placeholders: bool = True,
    include_psk: bool = False,
    include_ota: bool = False,
    min_size: int = 384,
) -> bytes:
    """Create a minimal syntactically and structurally valid ESP32 image with segment table."""
    if include_placeholders:
        payload = b"INIT_" + SSID_PLACEHOLDER + b"_MID_" + PASS_PLACEHOLDER
        if include_psk:
            payload += b"_PSK_" + NOISE_PSK_PLACEHOLDER
        if include_ota:
            payload += b"_OTA_" + OTA_PASSWORD_PLACEHOLDER
        payload += b"_TAIL"
    else:
        payload = b"INIT_WITHOUT_ANY_TARGET_PLACEHOLDERS_IN_FIRMWARE_PAYLOAD_TAIL"

    # Pad payload to ensure overall binary satisfies ESP32 min length (>= 256 bytes)
    if len(payload) + 24 + 33 < min_size:
        payload += b"\x00" * (min_size - (len(payload) + 24 + 33))

    seg_header = struct.pack("<II", 0x3FFB0000, len(payload))
    raw = bytearray(24)
    raw[0] = 0xE9  # ESP_IMAGE_MAGIC
    raw[1] = 1     # 1 RAM segment
    raw += seg_header + payload
    raw += bytearray(33)  # 1 byte XOR checksum + 32 bytes SHA-256

    recalculate_esp32_checksum(raw)
    recalculate_esp32_sha256(raw)
    return bytes(raw)


def create_synthetic_vesync_container(
    include_placeholders: bool = True,
    include_psk: bool = False,
    include_ota: bool = False,
    model: str = "PPF-R361S",
    version: str = "9.9.9",
) -> bytes:
    """Create a synthetically generated VeSync container wrapping a valid ESP32 binary."""
    raw = create_synthetic_esp32_binary(
        include_placeholders=include_placeholders,
        include_psk=include_psk,
        include_ota=include_ota,
    )
    return package_vesync_ota_container(raw, model=model, version=version)
