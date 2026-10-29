"""In-Memory Dynamic Firmware Patcher for PawSync Pet Feeder.

Performs zero-touch, in-place binary injection of user Wi-Fi credentials into
pre-compiled ESPHome transition binaries (pawsync_ota_update.bin) before serving
over the local VeSync staging HTTP server.

Recalculates hardware ESP32 segment XOR checksums, image SHA-256 digests, and
VeSync AES-128-CBC outer container headers on the fly (<50ms).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import string
import struct
import tempfile
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)


class FirmwarePatchError(Exception):
    """Raised when the firmware cannot be safely patched."""


# Fixed 32-byte SSID and 64-byte Password placeholder patterns
# (31 ASCII chars + \0 = 32 bytes; 63 ASCII chars + \0 = 64 bytes)
SSID_PLACEHOLDER = b"PAWSYNC_WIFI_SSID_PLACEHOLDER31\x00"
PASS_PLACEHOLDER = b"PAWSYNC_WIFI_PASSWORD_PLACEHOLDER_63_BYTES_LONG_BUFFER_BUFFER_X\x00"
NOISE_PSK_PLACEHOLDER = b"PLACEHOLDER_NOISE_PSK_KEY_44B_______________"
OTA_PASSWORD_PLACEHOLDER = b"PLACEHOLDER_OTA_PASSWORD_32B____"

MAX_SSID_LEN = 32
MAX_PASS_LEN = 64
MAX_NOISE_PSK_LEN = 44
MAX_OTA_PASS_LEN = 32
CONTAINER_HEADER_LEN = 129
ESP_IMAGE_MAGIC = 0xE9


def generate_noise_psk() -> str:
    """Generate a unique cryptographically secure 32-byte base64 Noise PSK."""
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def generate_ota_password(length: int = 16) -> str:
    """Generate a secure random alphanumeric OTA password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def safe_truncate_utf8(text: str, max_bytes: int) -> bytes:
    """Truncate to max_bytes while preserving valid UTF-8 and adding a null terminator."""
    if not text:
        return b"\x00" * (max_bytes + 1)
    encoded = text.encode("utf-8")
    while len(encoded) > max_bytes:
        text = text[:-1]
        encoded = text.encode("utf-8")
    return encoded.ljust(max_bytes + 1, b"\x00")


def can_patch_firmware(
    firmware_bytes: bytes,
    require_psk: bool = False,
    require_ota: bool = False,
) -> bool:
    """Return True if the firmware contains the target Wi-Fi and secret placeholders."""
    raw = (
        firmware_bytes[CONTAINER_HEADER_LEN:]
        if len(firmware_bytes) > CONTAINER_HEADER_LEN and firmware_bytes[0] == 0x01
        else firmware_bytes
    )
    if SSID_PLACEHOLDER not in raw or PASS_PLACEHOLDER not in raw:
        return False
    if require_psk and NOISE_PSK_PLACEHOLDER not in raw:
        return False
    if require_ota and OTA_PASSWORD_PLACEHOLDER not in raw:
        return False
    return True


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


def validate_esp32_image_structure(
    raw_bin: bytes,
    require_no_placeholders: bool = True,
    checked_placeholders: list[bytes] | None = None,
) -> bool:
    """Validate that raw ESP32 binary has a valid 0xE9 header, segment table, and no unpatched placeholders."""
    if not raw_bin or len(raw_bin) < 256:
        raise FirmwarePatchError(f"Firmware payload too small ({len(raw_bin) if raw_bin else 0} bytes)")

    if raw_bin[0] != ESP_IMAGE_MAGIC:
        raise FirmwarePatchError(f"Invalid ESP32 image magic byte: 0x{raw_bin[0]:02X} (expected 0xE9)")

    seg_count = raw_bin[1]
    if seg_count < 1 or seg_count > 16:
        raise FirmwarePatchError(f"Invalid ESP32 segment count: {seg_count} (expected 1..16)")

    offset = 24
    for i in range(seg_count):
        if offset + 8 > len(raw_bin):
            raise FirmwarePatchError(f"Truncated image: cannot read segment {i} header at offset {offset}")
        load_addr, seg_len = struct.unpack("<II", raw_bin[offset : offset + 8])
        offset += 8 + seg_len
        if offset > len(raw_bin):
            raise FirmwarePatchError(
                f"Segment {i} length {seg_len} at offset {offset} exceeds total binary size {len(raw_bin)}"
            )

    if require_no_placeholders:
        targets = checked_placeholders or [
            SSID_PLACEHOLDER,
            PASS_PLACEHOLDER,
            NOISE_PSK_PLACEHOLDER,
            OTA_PASSWORD_PLACEHOLDER,
        ]
        for placeholder in targets:
            if placeholder in raw_bin:
                raise FirmwarePatchError(
                    f"Structural validation failed: unpatched placeholder {placeholder[:16]!r} found in binary"
                )

    return True


def patch_raw_esp32_credentials(
    raw_bin: bytes,
    ssid: str,
    password: str,
    noise_psk: str | None = None,
    ota_password: str | None = None,
) -> bytes:
    """Inject user Wi-Fi credentials, Noise PSK, and OTA password into raw ESP32 binary and update hardware checksums."""
    if not ssid and not noise_psk and not ota_password:
        return raw_bin

    buf = bytearray(raw_bin)
    patched_placeholders: list[bytes] = []

    # 1. Wi-Fi credentials
    if ssid:
        idx_s = buf.find(SSID_PLACEHOLDER)
        idx_p = buf.find(PASS_PLACEHOLDER)
        if idx_s == -1 or idx_p == -1:
            raise FirmwarePatchError("Required Wi-Fi placeholders not found in firmware binary")
        ssid_bytes = safe_truncate_utf8(ssid, 31)
        pass_bytes = safe_truncate_utf8(password or "", 63)
        buf[idx_s : idx_s + MAX_SSID_LEN] = ssid_bytes
        buf[idx_p : idx_p + MAX_PASS_LEN] = pass_bytes
        patched_placeholders.extend([SSID_PLACEHOLDER, PASS_PLACEHOLDER])

    # 2. Noise PSK (44 bytes base64)
    if noise_psk:
        idx_k = buf.find(NOISE_PSK_PLACEHOLDER)
        if idx_k == -1:
            raise FirmwarePatchError("Required Noise PSK placeholder not found in firmware binary")
        psk_bytes = noise_psk.encode("ascii")
        if len(psk_bytes) != MAX_NOISE_PSK_LEN:
            raise FirmwarePatchError(
                f"Noise PSK length invalid: {len(psk_bytes)} bytes (expected {MAX_NOISE_PSK_LEN})"
            )
        buf[idx_k : idx_k + MAX_NOISE_PSK_LEN] = psk_bytes
        patched_placeholders.append(NOISE_PSK_PLACEHOLDER)

    # 3. OTA password (up to 31 bytes + \0 = 32 bytes)
    if ota_password:
        idx_o = buf.find(OTA_PASSWORD_PLACEHOLDER)
        if idx_o == -1:
            raise FirmwarePatchError("Required OTA password placeholder not found in firmware binary")
        ota_bytes = safe_truncate_utf8(ota_password, 31)
        buf[idx_o : idx_o + MAX_OTA_PASS_LEN] = ota_bytes
        patched_placeholders.append(OTA_PASSWORD_PLACEHOLDER)

    # Recalculate ROM bootloader checksum & image SHA-256 digest
    recalculate_esp32_checksum(buf)
    recalculate_esp32_sha256(buf)

    # Perform structural validation on patched ESP32 image
    validate_esp32_image_structure(
        bytes(buf),
        require_no_placeholders=True,
        checked_placeholders=patched_placeholders,
    )

    _LOGGER.info(
        "Dynamically patched ESP32 binary with Wi-Fi (SSID '%s'), Noise PSK (%s), OTA pass (%s)",
        ssid,
        "present" if noise_psk else "skipped",
        "present" if ota_password else "skipped",
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
    header[34 : 34 + len(model_bytes)] = model_bytes

    ver_bytes = version.encode("ascii")[:15]
    header[50 : 50 + len(ver_bytes)] = ver_bytes

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
    noise_psk: str | None = None,
    ota_password: str | None = None,
    model: str = "PPF-R361S",
    version: str = "9.9.9",
) -> bytes:
    """Extract raw ESP32 firmware from container, patch credentials, and re-package container."""
    if len(container_bytes) <= CONTAINER_HEADER_LEN or container_bytes[0] != 0x01:
        # Not a VeSync container, attempt patching as raw binary
        return patch_raw_esp32_credentials(
            container_bytes,
            ssid,
            password,
            noise_psk=noise_psk,
            ota_password=ota_password,
        )

    raw_bin = container_bytes[CONTAINER_HEADER_LEN:]
    patched_raw = patch_raw_esp32_credentials(
        raw_bin,
        ssid,
        password,
        noise_psk=noise_psk,
        ota_password=ota_password,
    )
    return package_vesync_ota_container(patched_raw, model=model, version=version)


def prepare_customized_firmware_file(
    source_path: str,
    target_dir: str,
    ssid: str | None,
    password: str | None,
    noise_psk: str | None = None,
    ota_password: str | None = None,
) -> str:
    """Prepare a customized firmware file with injected credentials, or return source path if unchanged."""
    if not ssid and not noise_psk and not ota_password:
        return source_path

    if not os.path.exists(source_path):
        raise FirmwarePatchError(f"Source firmware binary not found: {source_path}")

    with open(source_path, "rb") as f:
        content = f.read()

    require_psk = bool(noise_psk)
    require_ota = bool(ota_password)
    if not can_patch_firmware(content, require_psk=require_psk, require_ota=require_ota):
        raise FirmwarePatchError("Required placeholders not found in firmware binary")

    try:
        patched = patch_container_firmware(
            content,
            ssid or "",
            password or "",
            noise_psk=noise_psk,
            ota_password=ota_password,
        )
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
    except FirmwarePatchError:
        raise
    except Exception as err:
        _LOGGER.error("Could not customize firmware binary: %s", err)
        raise FirmwarePatchError(f"Firmware patching failed: {err}") from err
