"""In-Memory Dynamic Firmware Patcher for PawSync Pet Feeder.

Performs zero-touch, in-place binary injection of user Wi-Fi credentials into
pre-compiled ESPHome transition binaries (pawsync_ota_update.bin) before serving
over the local VeSync staging HTTP server.

Recalculates hardware ESP32 segment XOR checksums, image SHA-256 digests, and
VeSync AES-128-CBC outer container headers on the fly (<50ms).
"""

from __future__ import annotations

import hashlib
import logging
import os
import struct
import tempfile
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

# Fixed 32-byte SSID and 64-byte Password placeholder patterns
# (31 ASCII chars + \0 = 32 bytes; 63 ASCII chars + \0 = 64 bytes)
SSID_PLACEHOLDER = b"PAWSYNC_WIFI_SSID_PLACEHOLDER31\x00"
PASS_PLACEHOLDER = b"PAWSYNC_WIFI_PASSWORD_PLACEHOLDER_63_BYTES_LONG_BUFFER_BUFFER_X\x00"

MAX_SSID_LEN = 32
MAX_PASS_LEN = 64
CONTAINER_HEADER_LEN = 129
ESP_IMAGE_MAGIC = 0xE9


def can_patch_firmware(firmware_bytes: bytes) -> bool:
    """Return True if the firmware contains the target Wi-Fi credential placeholders."""
    raw = firmware_bytes[CONTAINER_HEADER_LEN:] if len(firmware_bytes) > CONTAINER_HEADER_LEN and firmware_bytes[0] == 0x01 else firmware_bytes
    return SSID_PLACEHOLDER in raw and PASS_PLACEHOLDER in raw


def recalculate_esp32_checksum(raw_bin: bytearray) -> int:
    """Recalculate the 8-bit XOR checksum across all RAM segments and write to binary."""
    chk = 0xEF
    offset = 24
    seg_count = raw_bin[1]
    for _ in range(seg_count):
        _, length = struct.unpack("<II", raw_bin[offset:offset + 8])
        seg_bytes = raw_bin[offset + 8:offset + 8 + length]
        offset += 8 + length
        for b in seg_bytes:
            chk ^= b
    raw_bin[-33] = chk
    return chk


def recalculate_esp32_sha256(raw_bin: bytearray) -> bytes:
    """Recalculate the 32-byte SHA-256 digest over the binary and write to trailing 32 bytes."""
    digest = hashlib.sha256(raw_bin[:-32]).digest()
    raw_bin[-32:] = digest
    return digest


def patch_raw_esp32_credentials(raw_bin: bytes, ssid: str, password: str) -> bytes:
    """Inject user Wi-Fi credentials into raw ESP32 binary and update hardware checksums."""
    if not ssid:
        return raw_bin

    buf = bytearray(raw_bin)
    idx_s = buf.find(SSID_PLACEHOLDER)
    idx_p = buf.find(PASS_PLACEHOLDER)

    if idx_s == -1 or idx_p == -1:
        _LOGGER.warning("Firmware binary does not contain dynamic Wi-Fi placeholders; skipping patch")
        return raw_bin

    # Prepare exact fixed-width null-padded byte buffers
    ssid_bytes = ssid.encode("utf-8")[:MAX_SSID_LEN].ljust(MAX_SSID_LEN, b"\x00")
    pass_bytes = (password or "").encode("utf-8")[:MAX_PASS_LEN].ljust(MAX_PASS_LEN, b"\x00")

    buf[idx_s:idx_s + MAX_SSID_LEN] = ssid_bytes
    buf[idx_p:idx_p + MAX_PASS_LEN] = pass_bytes

    # Recalculate ROM bootloader checksum & image SHA-256 digest
    recalculate_esp32_checksum(buf)
    recalculate_esp32_sha256(buf)

    _LOGGER.info(
        "Dynamically patched ESP32 binary with Wi-Fi SSID '%s' (32B) and password (64B)",
        ssid,
    )
    return bytes(buf)


def package_vesync_ota_container(
    raw_bin: bytes,
    model: str = "PPF-R361S",
    version: str = "9.9.9",
) -> bytes:
    """Wrap raw ESP32 binary into a cryptographically valid 129-byte VeSync OTA container."""
    md5_hex = hashlib.md5(raw_bin).hexdigest().upper().encode("ascii")
    header = bytearray(128)
    header[0] = 0x01
    header[1:33] = md5_hex
    header[33] = 0x00

    model_bytes = model.encode("ascii")[:15]
    header[34:34 + len(model_bytes)] = model_bytes

    ver_bytes = version.encode("ascii")[:15]
    header[50:50 + len(ver_bytes)] = ver_bytes

    header[66:70] = b"1.0\x00"
    header[74:76] = b"UN"

    key = hashlib.md5(b"Levoit").digest()
    iv = hashlib.md5(b"Levoit").digest()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    enc_header = encryptor.update(bytes(header)) + encryptor.finalize()

    return bytes([0x01]) + enc_header + raw_bin


def patch_container_firmware(
    container_bytes: bytes,
    ssid: str,
    password: str,
    model: str = "PPF-R361S",
    version: str = "9.9.9",
) -> bytes:
    """Extract raw ESP32 firmware from container, patch Wi-Fi, and re-package container."""
    if len(container_bytes) <= CONTAINER_HEADER_LEN or container_bytes[0] != 0x01:
        # Not a VeSync container, attempt patching as raw binary
        return patch_raw_esp32_credentials(container_bytes, ssid, password)

    raw_bin = container_bytes[CONTAINER_HEADER_LEN:]
    patched_raw = patch_raw_esp32_credentials(raw_bin, ssid, password)
    return package_vesync_ota_container(patched_raw, model=model, version=version)


def prepare_customized_firmware_file(
    source_path: str,
    target_dir: str,
    ssid: str | None,
    password: str | None,
) -> str:
    """Prepare a customized firmware file with injected credentials, or return source path if unchanged."""
    if not ssid:
        return source_path

    if not os.path.exists(source_path):
        return source_path

    try:
        with open(source_path, "rb") as f:
            content = f.read()

        if not can_patch_firmware(content):
            _LOGGER.info("Firmware does not contain patch placeholders; using unpatched binary")
            return source_path

        patched = patch_container_firmware(content, ssid, password or "")
        os.makedirs(target_dir, exist_ok=True)
        dest_path = os.path.join(target_dir, "pawsync_ota_customized.bin")
        with open(dest_path, "wb") as f:
            f.write(patched)

        _LOGGER.info(
            "Prepared customized zero-touch firmware container at %s (%d bytes)",
            dest_path,
            len(patched),
        )
        return dest_path
    except Exception as err:
        _LOGGER.warning("Could not customize firmware binary with Wi-Fi credentials: %s", err)
        return source_path
