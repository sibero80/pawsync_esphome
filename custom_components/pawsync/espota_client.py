"""Async ESPHome OTA Flasher Client for PawSync Feeder."""

from __future__ import annotations

import asyncio
import hashlib
import logging
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

UPLOAD_BLOCK_SIZE = 4096


async def async_flash_esphome_ota(
    host: str,
    firmware_binary: bytes,
    port: int = OTA_PORT,
    on_progress: Callable[[float], None] | None = None,
    timeout: float = 30.0,
) -> bool:
    """Flash an ESPHome device via its native OTA port (3232)."""
    _LOGGER.info(
        "Starting ESPHome OTA update to %s:%d (%d bytes)...",
        host,
        port,
        len(firmware_binary),
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
            _LOGGER.error("Bad OTA header response: 0x%02X", header[0])
            return False
        version = header[1]
        _LOGGER.debug("Connected to ESPHome OTA (protocol version %d)", version)

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
            _ = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]

        # 4. Auth check
        auth_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
        if auth_resp != RESPONSE_AUTH_OK:
            _LOGGER.error(
                "ESP requested authentication but no password configured (auth code 0x%02X)",
                auth_resp,
            )
            return False

        # 5. Send ota_type if extended protocol
        if extended_proto:
            writer.write(bytes([0x00]))  # 0x00 = OTA_TYPE_UPDATE_APP
            await writer.drain()

        # 6. Send binary size (4 bytes big-endian)
        upload_size = len(firmware_binary)
        size_bytes = upload_size.to_bytes(4, byteorder="big")
        writer.write(size_bytes)
        await writer.drain()

        # Device erases flash here; allow up to 45 seconds timeout
        prepare_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=45.0))[0]
        if prepare_resp != RESPONSE_UPDATE_PREPARE_OK:
            _LOGGER.error("OTA prepare failed on device: 0x%02X", prepare_resp)
            return False

        # 7. Send MD5 checksum
        md5_hash = hashlib.md5(firmware_binary).hexdigest().encode("ascii")
        writer.write(md5_hash)
        await writer.drain()

        md5_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=10.0))[0]
        if md5_resp != RESPONSE_BIN_MD5_OK:
            _LOGGER.error("OTA MD5 check failed on device: 0x%02X", md5_resp)
            return False

        # 8. Send Binary in chunks
        offset = 0
        while offset < upload_size:
            chunk = firmware_binary[offset : offset + UPLOAD_BLOCK_SIZE]
            writer.write(chunk)
            await writer.drain()
            offset += len(chunk)

            if version >= 2:
                chunk_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=15.0))[0]
                if chunk_resp != RESPONSE_CHUNK_OK:
                    _LOGGER.error("OTA chunk rejected at offset %d: 0x%02X", offset, chunk_resp)
                    return False

            if on_progress:
                on_progress(offset / upload_size)

        # 9. Wait for end verification and commit
        receive_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=20.0))[0]
        if receive_resp != RESPONSE_RECEIVE_OK:
            _LOGGER.error("OTA receive failed: 0x%02X", receive_resp)
            return False

        end_resp = (await asyncio.wait_for(reader.readexactly(1), timeout=20.0))[0]
        if end_resp != RESPONSE_UPDATE_END_OK:
            _LOGGER.error("OTA end commit failed: 0x%02X", end_resp)
            return False

        # 10. Send Final OK ACK
        try:
            writer.write(bytes([RESPONSE_OK]))
            await writer.drain()
        except Exception:
            # Device may reboot immediately
            pass

        _LOGGER.info("ESPHome OTA upload successful! Device is rebooting into new firmware.")
        return True

    except Exception as err:
        _LOGGER.error("ESPHome OTA upload exception: %s", err)
        return False
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
