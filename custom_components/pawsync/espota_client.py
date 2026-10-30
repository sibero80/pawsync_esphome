"""Async ESPHome OTA Flasher Client for PawSync Feeder."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from typing import Callable

_LOGGER = logging.getLogger(__name__)

OTA_PORT = 3232
MAGIC_BYTES = bytes([0x6C, 0x26, 0xF7, 0x5C, 0x45])

RESPONSE_OK = 0x00
RESPONSE_REQUEST_AUTH = 0x01
RESPONSE_REQUEST_SHA256_AUTH = 0x02
RESPONSE_HEADER_OK = 0x40
RESPONSE_AUTH_OK = 0x41
RESPONSE_UPDATE_PREPARE_OK = 0x42
RESPONSE_BIN_MD5_OK = 0x43
RESPONSE_RECEIVE_OK = 0x44
RESPONSE_UPDATE_END_OK = 0x45
RESPONSE_SUPPORTS_COMPRESSION = 0x46
RESPONSE_CHUNK_OK = 0x47
RESPONSE_FEATURE_FLAGS = 0x48

CLIENT_FEATURE_SUPPORTS_COMPRESSION = 0x01
CLIENT_FEATURE_SUPPORTS_SHA256_AUTH = 0x02
CLIENT_FEATURE_SUPPORTS_EXTENDED_PROTOCOL = 0x04
CLIENT_FEATURE_SUPPORTS_NOISE = 0x08

SERVER_FEATURE_SUPPORTS_COMPRESSION = 0x01
SERVER_FEATURE_SUPPORTS_PARTITION_ACCESS = 0x02
SERVER_FEATURE_SUPPORTS_NOISE = 0x04

OTA_TYPE_UPDATE_APP = 0x00

# ESPHome native OTA block size is 8192 bytes
UPLOAD_BLOCK_SIZE = 8192

# Human-readable ESPHome OTA error messages
ERROR_MESSAGES: dict[int, str] = {
    0x80: "Invalid magic byte",
    0x81: "Device couldn't prepare flash memory for update",
    0x82: "Authentication invalid - password rejected",
    0x83: "Writing OTA data to flash memory failed",
    0x84: "Finishing update commit failed",
    0x85: "Manual reset required on first OTA after USB flash",
    0x86: "Device flashed with wrong flash size",
    0x87: "Device does not have requested flash size",
    0x88: "ESP8266 does not have enough space",
    0x89: "ESP32 OTA partition is too small",
    0x8A: "OTA partition on device couldn't be found",
    0x8B: "Firmware MD5 checksum mismatch",
    0x8C: "RP2040 does not have enough space",
    0x8D: "Firmware signature invalid",
    0x8E: "Requested OTA type is not supported by device",
    0x93: "OTA downgrade protection enabled: new version must be newer",
    0x94: "Device requires encrypted OTA connection",
    0xFF: "Unknown error from ESP",
}


def sanitize_firmware_binary(firmware_binary: bytes) -> bytes:
    """Ensure firmware binary is stripped of any VeSync container header."""
    if len(firmware_binary) > 129 and firmware_binary[0] != 0xE9 and firmware_binary[129] == 0xE9:
        _LOGGER.info(
            "Detected 129-byte VeSync container header; stripped for ESPHome native OTA (size: %d -> %d bytes)",
            len(firmware_binary),
            len(firmware_binary) - 129,
        )
        return firmware_binary[129:]
    return firmware_binary


async def async_flash_esphome_ota(
    host: str,
    firmware_binary: bytes,
    port: int = OTA_PORT,
    ota_password: str | None = None,
    noise_psk: str | None = None,
    on_progress: Callable[[float], None] | None = None,
    timeout: float = 30.0,
) -> bool:
    """Flash an ESPHome device via its native OTA port (3232)."""
    # 0. Sanitize binary
    firmware_binary = sanitize_firmware_binary(firmware_binary)
    if not firmware_binary or firmware_binary[0] != 0xE9:
        _LOGGER.error(
            "Cannot flash invalid firmware: expected ESP32 magic byte 0xE9, got 0x%02X",
            firmware_binary[0] if firmware_binary else 0,
        )
        return False

    upload_size = len(firmware_binary)
    _LOGGER.info(
        "Starting ESPHome OTA update to %s:%d (%d bytes)...",
        host,
        port,
        upload_size,
    )

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except Exception as err:
        _LOGGER.error("Failed to connect to ESPHome OTA port on %s:%d: %s", host, port, err)
        return False

    try:
        # 1. Send Magic Bytes
        writer.write(MAGIC_BYTES)
        await writer.drain()

        # 2. Receive Version
        header = await asyncio.wait_for(reader.readexactly(2), timeout=10.0)
        if header[0] != RESPONSE_OK:
            err_msg = ERROR_MESSAGES.get(header[0], f"Unknown error code 0x{header[0]:02X}")
            _LOGGER.error("Bad OTA header response from %s: %s", host, err_msg)
            return False
        version = header[1]
        _LOGGER.info("Connected to ESPHome OTA on %s (protocol version %d)", host, version)

        # 3. Features negotiation
        features_to_send = (
            CLIENT_FEATURE_SUPPORTS_COMPRESSION
            | CLIENT_FEATURE_SUPPORTS_SHA256_AUTH
            | CLIENT_FEATURE_SUPPORTS_EXTENDED_PROTOCOL
        )
        writer.write(bytes([features_to_send]))
        await writer.drain()

        features_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
        extended_proto = False
        if features_resp == RESPONSE_FEATURE_FLAGS:
            extended_proto = True
            server_flags = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
            _LOGGER.debug("Server feature flags from %s: 0x%02X", host, server_flags)
        elif features_resp in ERROR_MESSAGES:
            _LOGGER.error("Feature negotiation failed on %s: %s", host, ERROR_MESSAGES[features_resp])
            return False

        # 4. Auth check
        auth_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
        if auth_resp == RESPONSE_REQUEST_SHA256_AUTH:
            passwords_to_try: list[str] = []
            if ota_password:
                passwords_to_try.append(ota_password)
            # Default placeholder fallback for feeders previously flashed with unpatched image
            if "PLACEHOLDER_OTA_PASSWORD_32B____" not in passwords_to_try:
                passwords_to_try.append("PLACEHOLDER_OTA_PASSWORD_32B____")

            passed_auth = False
            for idx, candidate_pass in enumerate(passwords_to_try):
                if idx > 0:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(host, port), timeout=timeout
                        )
                        writer.write(MAGIC_BYTES)
                        await writer.drain()
                        header = await asyncio.wait_for(reader.readexactly(2), timeout=10.0)
                        if header[0] != RESPONSE_OK:
                            return False
                        writer.write(bytes([features_to_send]))
                        await writer.drain()
                        features_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
                        if features_resp == RESPONSE_FEATURE_FLAGS:
                            server_flags = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
                        auth_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
                        if auth_resp != RESPONSE_REQUEST_SHA256_AUTH:
                            break
                    except Exception as err:
                        _LOGGER.error("Failed reconnecting to %s for password retry: %s", host, err)
                        return False

                # Read 64 hex bytes nonce
                nonce_bytes = await asyncio.wait_for(reader.readexactly(64), timeout=10.0)
                nonce = nonce_bytes.decode("ascii")
                # Generate client nonce (64 hex characters)
                cnonce = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
                # Calculate SHA256(password + nonce + cnonce)
                to_hash = candidate_pass.encode("utf-8") + nonce.encode("ascii") + cnonce.encode("ascii")
                resp_hash = hashlib.sha256(to_hash).hexdigest()
                # Send cnonce + resp_hash (128 bytes total)
                writer.write(cnonce.encode("ascii") + resp_hash.encode("ascii"))
                await writer.drain()
                # Server sends verification response
                auth_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
                if auth_resp == RESPONSE_AUTH_OK:
                    passed_auth = True
                    if candidate_pass == "PLACEHOLDER_OTA_PASSWORD_32B____" and candidate_pass != ota_password:
                        _LOGGER.warning(
                            "Device at %s authenticated using placeholder fallback OTA password; self-healing in progress",
                            host,
                        )
                    break

            if not passed_auth or auth_resp != RESPONSE_AUTH_OK:
                err_desc = ERROR_MESSAGES.get(auth_resp, f"Auth code 0x{auth_resp:02X}")
                _LOGGER.error("Authentication rejected on %s: %s", host, err_desc)
                return False

        if auth_resp != RESPONSE_AUTH_OK:
            err_desc = ERROR_MESSAGES.get(auth_resp, f"Auth code 0x{auth_resp:02X}")
            _LOGGER.error("Authentication rejected on %s: %s", host, err_desc)
            return False

        # 5. Send ota_type if extended protocol
        if extended_proto:
            writer.write(bytes([OTA_TYPE_UPDATE_APP]))
            await writer.drain()

        # 6. Send binary size (4 bytes big-endian)
        size_bytes = upload_size.to_bytes(4, byteorder="big")
        writer.write(size_bytes)
        await writer.drain()

        # Device erases flash partition here; allow up to 60 seconds timeout
        t0 = time.time()
        _LOGGER.info("Preparing device flash for %d bytes...", upload_size)
        prepare_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=60.0))[0]
        if prepare_resp != RESPONSE_UPDATE_PREPARE_OK:
            err_desc = ERROR_MESSAGES.get(prepare_resp, f"Code 0x{prepare_resp:02X}")
            _LOGGER.error("OTA prepare failed on %s: %s", host, err_desc)
            return False
        _LOGGER.info("Device flash prepared in %.2f seconds", time.time() - t0)

        # 7. Send MD5 checksum
        md5_hash = hashlib.md5(firmware_binary).hexdigest().encode("ascii")
        writer.write(md5_hash)
        await writer.drain()

        md5_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
        if md5_resp != RESPONSE_BIN_MD5_OK:
            err_desc = ERROR_MESSAGES.get(md5_resp, f"Code 0x{md5_resp:02X}")
            _LOGGER.error("OTA MD5 check failed on %s: %s", host, err_desc)
            return False

        # 8. Send Binary in chunks with synchronized ESPHome v2 ACKs
        offset = 0
        size_acknowledged = 0
        _LOGGER.info("Uploading %d bytes in %d-byte chunks...", upload_size, UPLOAD_BLOCK_SIZE)

        while offset < upload_size:
            chunk = firmware_binary[offset : offset + UPLOAD_BLOCK_SIZE]
            writer.write(chunk)
            await writer.drain()
            offset += len(chunk)

            if version >= 2:
                # ESPHome v2 sends RESPONSE_CHUNK_OK every OTA_BLOCK_SIZE (8192 bytes),
                # and/or when total == ota_size.
                while (size_acknowledged + UPLOAD_BLOCK_SIZE <= offset) or (
                    offset == upload_size and size_acknowledged < upload_size
                ):
                    chunk_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=20.0))[0]
                    if chunk_resp != RESPONSE_CHUNK_OK:
                        err_desc = ERROR_MESSAGES.get(chunk_resp, f"Code 0x{chunk_resp:02X}")
                        _LOGGER.error("OTA chunk rejected at offset %d: %s", offset, err_desc)
                        return False
                    size_acknowledged += UPLOAD_BLOCK_SIZE

            if on_progress:
                on_progress(offset / upload_size)

        # 9. Wait for end verification and commit
        _LOGGER.info("Upload complete. Waiting for device flash verification and commit...")
        receive_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=30.0))[0]
        if receive_resp != RESPONSE_RECEIVE_OK:
            err_desc = ERROR_MESSAGES.get(receive_resp, f"Code 0x{receive_resp:02X}")
            _LOGGER.error("OTA receive verification failed on %s: %s", host, err_desc)
            return False

        end_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=30.0))[0]
        if end_resp != RESPONSE_UPDATE_END_OK:
            err_desc = ERROR_MESSAGES.get(end_resp, f"Code 0x{end_resp:02X}")
            _LOGGER.error("OTA end commit failed on %s: %s", host, err_desc)
            return False

        # 10. Send Final OK ACK
        try:
            writer.write(bytes([RESPONSE_OK]))
            await writer.drain()
        except Exception:
            # Device often closes connection immediately upon reboot
            pass

        _LOGGER.info("ESPHome OTA upload successful! Device %s is rebooting into new firmware.", host)
        return True

    except Exception as err:
        _LOGGER.error("ESPHome OTA upload exception for %s: %s", host, err)
        return False
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
