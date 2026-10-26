"""VeSync / Pawsync Cloud Bypass Command Relay for Feeder Adoption."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

import aiohttp

from .const import (
    DEFAULT_MODEL,
    PAWSYNC_API_BASE,
    VESYNC_API_BASE,
)
from .ota_stager import format_staging_url

_LOGGER = logging.getLogger(__name__)


class VeSyncRelay:
    """Async relay to send bypass commands to the feeder through Pawsync/VeSync Cloud."""

    def __init__(
        self,
        account_id: str,
        token: str,
        session: aiohttp.ClientSession | None = None,
        api_base: str = PAWSYNC_API_BASE,
    ) -> None:
        """Initialize the relay."""
        self.account_id = account_id
        self.token = token
        self._session = session
        self._own_session = False
        self.api_base = api_base

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or getattr(self._session, "closed", False) is True:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not getattr(self._session, "closed", False):
            await self._session.close()

    async def async_trigger_ota(
        self,
        cid: str,
        download_url: str,
        model: str = DEFAULT_MODEL,
        version: str = "9.9.9",
        url_mode: str = "dword",
    ) -> dict[str, Any]:
        """
        Send upFirmware bypass command to the feeder via Pawsync / VeSync cloud.
        Formats the URL using DWORD IP or sslip to ensure lwIP socket compatibility.
        """
        formatted_url = format_staging_url(download_url, mode=url_mode)
        _LOGGER.info("Dispatching OTA trigger for CID %s with URL: %s", cid, formatted_url)

        command_data = {
            "pluginName": "mainFw",
            "url": formatted_url,
            "newVersion": version,
            "upMode": 2,
        }

        return await self.async_send_bypass(
            cid=cid,
            method="upFirmware",
            command_data=command_data,
            model=model,
        )

    async def async_send_bypass(
        self,
        cid: str,
        method: str,
        command_data: dict[str, Any],
        model: str = DEFAULT_MODEL,
    ) -> dict[str, Any]:
        """
        Construct and dispatch bypassV2 payload to deviceManaged/v1/bypassV2.
        Wire structure conforms to Android APK h6.b.f specification.
        """
        trace_id = f"PET0001{int(time.time() * 1000)}-00001"
        endpoint = f"{self.api_base}/pet/api/deviceManaged/v1/bypassV2"

        body = {
            "traceId": trace_id,
            "method": "bypassV2",
            "accountID": self.account_id,
            "token": self.token,
            "timeZone": "America/New_York",
            "userCountryCode": "US",
            "acceptLanguage": "en",
            "debugMode": False,
            "osInfo": "Android 14",
            "clientType": "pawsync",
            "clientVersion": "1.1.32",
            "terminalId": hashlib.md5(self.account_id.encode("utf-8")).hexdigest(),
            "clientInfo": "pawsync",
            "appID": "psybfyca",
            "appVersion": "1.1.32",
            "phoneOS": "Android 14",
            "phoneBrand": "Android",
            "cid": cid,
            "configModule": model,
            "payload": {
                "method": method,
                "source": "APP",
                "data": {
                    "cid": cid,
                    "configModule": model,
                    **command_data,
                },
            },
        }

        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "okhttp/3.14.9",
        }

        session = await self._get_session()
        try:
            async with session.post(
                endpoint,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                _LOGGER.debug("BypassV2 response from cloud: %s", data)
                return data
        except Exception as err:
            _LOGGER.warning("Cloud bypass failed via %s: %s", self.api_base, err)
            # Try VeSync fallback if Pawsync failed
            if self.api_base != VESYNC_API_BASE:
                _LOGGER.info("Retrying bypass via VeSync fallback (%s)...", VESYNC_API_BASE)
                self.api_base = VESYNC_API_BASE
                return await self.async_send_bypass(cid, method, command_data, model)
            return {"code": -1, "msg": str(err)}
