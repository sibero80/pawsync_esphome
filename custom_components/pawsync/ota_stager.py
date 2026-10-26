"""Local HTTP OTA Stager for Pawsync Feeder Wireless Conversion."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from typing import Callable

from aiohttp import web

from .const import (
    CHUNK_SIZE,
    DEFAULT_STAGING_PORT,
    HEADER_LEN,
    PACE_CHUNK_DELAY_SEC,
    PACE_INITIAL_PAUSE_SEC,
)

_LOGGER = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Detect local IP address of the Home Assistant host."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def format_staging_url(url: str, mode: str = "dword") -> str:
    """
    Format staging URL for embedded lwIP / inet_addr compatibility:
    - 'dword': Converts 192.168.1.140 into integer DWORD 3232235916.
    - 'sslip': Converts 192.168.1.140 into 192-168-1-140.sslip.io FQDN.
    - 'raw': Leaves unchanged.
    """
    import re
    import struct

    m = re.match(r"^(https?://)(\d+\.\d+\.\d+\.\d+)(:\d+)?(/.*)?$", url)
    if not m or mode == "raw":
        return url

    scheme, ip, port, path = m.groups()
    if mode == "dword":
        try:
            dword_ip = struct.unpack("!I", socket.inet_aton(ip))[0]
            return f"{scheme}{dword_ip}{port or ''}{path or ''}"
        except Exception as err:
            _LOGGER.warning("Could not convert IP %s to DWORD: %s", ip, err)
            return url
    elif mode == "sslip":
        dashed_ip = ip.replace(".", "-")
        return f"{scheme}{dashed_ip}.sslip.io{port or ''}{path or ''}"

    return url


class PawsyncOtaStager:
    """
    Paced HTTP Staging Server tailored for Pawsync PPF-R361S stock OTA client.
    Enforces exact 129-byte initial header, 8-second SPI flash erase pause,
    and 2KB chunk streaming with pacing.
    """

    def __init__(
        self,
        firmware_path: str,
        port: int = DEFAULT_STAGING_PORT,
        on_progress: Callable[[float, int, int], None] | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the stager."""
        self.firmware_path = firmware_path
        self.port = port
        self.on_progress = on_progress
        self.on_complete = on_complete
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._is_running = False
        self._transfer_started = False
        self._transfer_finished = False

    @property
    def is_running(self) -> bool:
        """Return True if stager is listening."""
        return self._is_running

    async def async_start(self) -> str:
        """Start the local staging HTTP server and return the download URL."""
        if not os.path.exists(self.firmware_path):
            raise FileNotFoundError(f"Firmware binary not found at {self.firmware_path}")

        self._app = web.Application()
        self._app.router.add_get("/firmware.bin", self._handle_download)
        self._app.router.add_get("/pawsync_ota_update.bin", self._handle_download)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        # Attempt to bind to requested port, fallback to dynamic if busy
        try:
            self._site = web.TCPSite(self._runner, "0.0.0.0", self.port)
            await self._site.start()
        except OSError:
            _LOGGER.warning("Port %d is in use, falling back to random available port", self.port)
            self._site = web.TCPSite(self._runner, "0.0.0.0", 0)
            await self._site.start()
            # Retrieve assigned port
            for server in self._site._server.sockets:
                self.port = server.getsockname()[1]
                break

        self._is_running = True
        local_ip = get_local_ip()
        url = f"http://{local_ip}:{self.port}/firmware.bin"
        _LOGGER.info("Pawsync OTA Stager listening at %s", url)
        return url

    async def async_stop(self) -> None:
        """Stop the staging HTTP server."""
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._is_running = False
        _LOGGER.info("Pawsync OTA Stager stopped")

    async def _handle_download(self, request: web.Request) -> web.StreamResponse:
        """Handle incoming download request from the stock feeder."""
        client_ip = request.remote or "unknown"
        _LOGGER.info("Pawsync Feeder (%s) connected to download firmware", client_ip)
        self._transfer_started = True

        total_size = os.path.getsize(self.firmware_path)
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(total_size),
                "Connection": "close",
            },
        )
        await response.prepare(request)

        bytes_sent = 0
        t0 = time.time()

        try:
            with open(self.firmware_path, "rb") as f:
                # Chunk 1: Send EXACTLY 129 bytes (the encrypted VeSync header)
                # The stock firmware's main_dev_fw_dl_cb asserts accumulated_header == 129.
                hdr = f.read(HEADER_LEN)
                if hdr:
                    await response.write(hdr)
                    bytes_sent += len(hdr)
                    _LOGGER.info(
                        "Dispatched exact %d-byte VeSync header to %s. Pacing %.1fs for SPI flash partition erase...",
                        len(hdr),
                        client_ip,
                        PACE_INITIAL_PAUSE_SEC,
                    )
                    if self.on_progress:
                        self.on_progress(bytes_sent / total_size, bytes_sent, total_size)
                    await asyncio.sleep(PACE_INITIAL_PAUSE_SEC)

                # Subsequent chunks: Stream in 2048-byte chunks with ~20ms delay
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    await response.write(chunk)
                    bytes_sent += len(chunk)

                    if self.on_progress and bytes_sent % (64 * 1024) < CHUNK_SIZE:
                        self.on_progress(bytes_sent / total_size, bytes_sent, total_size)

                    await asyncio.sleep(PACE_CHUNK_DELAY_SEC)

            elapsed = time.time() - t0
            _LOGGER.info(
                "Completed streaming %d bytes to %s in %.2fs (%.1f KB/s)",
                bytes_sent,
                client_ip,
                elapsed,
                (bytes_sent / 1024) / elapsed if elapsed > 0 else 0,
            )

            # Linger up to 10 seconds for device to finish writing flash and close cleanly
            await asyncio.sleep(10.0)
            self._transfer_finished = True
            if self.on_complete:
                self.on_complete()

        except Exception as err:
            _LOGGER.warning("Connection error streaming to %s: %s", client_ip, err)
            raise

        return response
