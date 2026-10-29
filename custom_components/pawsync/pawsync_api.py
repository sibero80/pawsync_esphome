"""Asynchronous API Client for Pawsync and VeSync Cloud Services."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    DEFAULT_COUNTRY_CODE,
    DEFAULT_TIME_ZONE,
    PAWSYNC_API_BASE,
    VESYNC_API_BASE,
)

_LOGGER = logging.getLogger(__name__)


class PawsyncError(Exception):
    """Base exception for Pawsync API errors."""


class PawsyncAuthError(PawsyncError):
    """Raised when authentication fails."""


class PawsyncConnectionError(PawsyncError):
    """Raised when connection to cloud fails."""


def generate_trace_id() -> str:
    """Generate a unique trace ID conforming to Pawsync pet app format."""
    millis = int(time.time() * 1000)
    rand_suffix = str(uuid.uuid4()).replace("-", "")[:5]
    return f"PET{rand_suffix}{millis}-00001"


def resolve_ip_from_mac(mac: str, hass: Any = None) -> str:
    """Resolve local IP address from MAC address using multi-tiered discovery:

    1. Home Assistant active entries and pending discovery flows (if hass provided)
    2. Linux /proc/net/arp cache
    3. System neighbor CLI tools (ip neigh / arp) for containerized or non-Linux hosts
    """
    if not mac:
        return ""
    clean_target = mac.replace(":", "").replace("-", "").strip().lower()

    # 1. Tier 1: Check Home Assistant context
    if hass is not None:
        try:
            if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_entries"):
                for entry in hass.config_entries.async_entries("esphome"):
                    entry_uid = (getattr(entry, "unique_id", None) or "").replace(":", "").replace("-", "").strip().lower()
                    if entry_uid and entry_uid == clean_target:
                        ip = entry.data.get("host")
                        if ip and ip != "0.0.0.0":
                            return str(ip)
            if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "flow"):
                flows = hass.config_entries.flow.async_progress_by_handler("esphome")
                for flow in flows:
                    ctx = flow.get("context", {})
                    flow_uid = (ctx.get("unique_id") or "").replace(":", "").replace("-", "").strip().lower()
                    if flow_uid and flow_uid == clean_target:
                        placeholders = ctx.get("title_placeholders", {})
                        ip = placeholders.get("ip") or flow.get("data", {}).get("host")
                        if ip and ip != "0.0.0.0":
                            return str(ip)
        except Exception as err:
            _LOGGER.debug("Could not inspect Home Assistant context for MAC %s: %s", mac, err)

    # 2. Tier 2: Check /proc/net/arp (fastest on Linux)
    try:
        if os.path.exists("/proc/net/arp"):
            with open("/proc/net/arp", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip_candidate = parts[0]
                        arp_mac = parts[3].replace(":", "").replace("-", "").strip().lower()
                        if arp_mac == clean_target and ip_candidate != "0.0.0.0":
                            return ip_candidate
    except Exception as err:
        _LOGGER.debug("Could not read /proc/net/arp: %s", err)

    # 3. Tier 3: CLI neighbor lookup (ip neigh or arp) for containers / macOS / BSD
    try:
        ip_cmd = shutil.which("ip")
        if ip_cmd:
            res = subprocess.run(
                [ip_cmd, "-4", "neigh", "show"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3].lower() == "lladdr":
                    ip_candidate = parts[0]
                    neigh_mac = parts[4].replace(":", "").replace("-", "").strip().lower()
                    if neigh_mac == clean_target and ip_candidate != "0.0.0.0":
                        return ip_candidate
    except Exception as err:
        _LOGGER.debug("Could not query 'ip neigh': %s", err)

    try:
        arp_cmd = shutil.which("arp")
        if arp_cmd:
            res = subprocess.run(
                [arp_cmd, "-an"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            for line in res.stdout.splitlines():
                match = re.search(r"\(([\d\.]+)\)\s+at\s+([0-9a-fA-F:]{17}|[0-9a-fA-F-]{17})", line)
                if match:
                    ip_candidate = match.group(1)
                    arp_mac = match.group(2).replace(":", "").replace("-", "").strip().lower()
                    if arp_mac == clean_target and ip_candidate != "0.0.0.0":
                        return ip_candidate
    except Exception as err:
        _LOGGER.debug("Could not query 'arp': %s", err)

    return ""


class PawsyncApiClient:
    """Async API Client for Pawsync / VeSync."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        country_code: str = DEFAULT_COUNTRY_CODE,
        time_zone: str = DEFAULT_TIME_ZONE,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._own_session = False
        self.country_code = country_code
        self.time_zone = time_zone
        self.account_id: str | None = None
        self.token: str | None = None
        self.auth_source: str | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp ClientSession."""
        if self._session is None or getattr(self._session, "closed", False) is True:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def close(self) -> None:
        """Close the session if locally owned."""
        if self._own_session and self._session and not getattr(self._session, "closed", False):
            await self._session.close()

    async def async_login(
        self,
        email: str,
        password: str,
        country_code: str | None = None,
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        """
        Authenticate against Pawsync Cloud (SHA-256) with VeSync Cloud (MD5) fallback.
        Returns dict with account_id, token, and auth source.
        """
        country = country_code or self.country_code
        tz = time_zone or self.time_zone

        # Try 1: Pawsync Cloud (smartapi.pawsync.com)
        try:
            res = await self._async_login_pawsync(email, password, country, tz)
            if res:
                self.account_id = res["account_id"]
                self.token = res["token"]
                self.auth_source = "pawsync"
                self.country_code = country
                self.time_zone = tz
                return res
        except PawsyncAuthError:
            raise
        except Exception as err:
            _LOGGER.debug("Pawsync native cloud login attempt failed: %s", err)

        # Try 2: VeSync Cloud Fallback (smartapi.vesync.com)
        try:
            res = await self._async_login_vesync(email, password, tz)
            if res:
                self.account_id = res["account_id"]
                self.token = res["token"]
                self.auth_source = "vesync"
                self.country_code = country
                self.time_zone = tz
                return res
        except Exception as err:
            _LOGGER.error("VeSync fallback login failed: %s", err)
            raise PawsyncAuthError(f"Login failed for {email}: {err}") from err

        raise PawsyncAuthError("Invalid username, password, or account region.")

    async def _async_login_pawsync(
        self,
        email: str,
        password: str,
        country_code: str,
        time_zone: str,
    ) -> dict[str, Any] | None:
        """Login to smartapi.pawsync.com using SHA-256."""
        endpoint = f"{PAWSYNC_API_BASE}/pet/api/userManaged/v1/login"
        trace_id = generate_trace_id()
        hashed_password = hashlib.sha256(password.encode("utf-8")).hexdigest()

        payload = {
            "context": {
                "traceId": trace_id,
                "method": "login",
                "token": "",
                "accountID": "",
                "timeZone": time_zone,
                "userCountryCode": country_code,
                "acceptLanguage": "en",
                "debugMode": False,
                "osInfo": "Android 14",
                "clientType": "pawsync",
                "clientVersion": "1.1.32",
                "terminalId": hashlib.md5(email.encode("utf-8")).hexdigest(),
                "clientInfo": "pawsync",
                "appID": "psybfyca",
                "appVersion": "1.1.32",
                "phoneOS": "Android 14",
                "phoneBrand": "Android",
            },
            "data": {
                "email": email,
                "password": hashed_password,
            },
        }

        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "okhttp/3.14.9",
            "traceId": trace_id,
            "bizType": "pet",
            "accountID": "",
            "token": "",
        }

        session = await self._get_session()
        try:
            async with session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    _LOGGER.warning("Pawsync login HTTP %s: %s", resp.status, text)
                    return None

                data = await resp.json()
                code = data.get("code")
                msg = data.get("msg", "")

                if code == 0 and "result" in data and data["result"]:
                    result = data["result"]
                    account_id = result.get("accountId") or result.get("accountID")
                    token = result.get("token")
                    if account_id and token:
                        return {
                            "account_id": str(account_id),
                            "token": str(token),
                            "source": "pawsync",
                            "country_code": result.get("countryCode", country_code),
                            "time_zone": result.get("timeZone", time_zone),
                        }
                elif code in (-11001, -11002, 11000):
                    raise PawsyncAuthError(f"Authentication failed: {msg} (code {code})")
                else:
                    _LOGGER.debug("Pawsync login non-zero response: %s", data)
                    return None
        except asyncio.TimeoutError as err:
            raise PawsyncConnectionError("Timeout connecting to Pawsync Cloud") from err
        except aiohttp.ClientError as err:
            raise PawsyncConnectionError(f"Network error connecting to Pawsync: {err}") from err

    async def _async_login_vesync(
        self,
        email: str,
        password: str,
        time_zone: str,
    ) -> dict[str, Any] | None:
        """Login to smartapi.vesync.com using MD5."""
        endpoint = f"{VESYNC_API_BASE}/cloud/v1/user/login"
        trace_id = generate_trace_id()
        hashed_password = hashlib.md5(password.encode("utf-8")).hexdigest()

        payload = {
            "acceptLanguage": "en",
            "account": email,
            "appVersion": "2.5.1",
            "method": "login",
            "password": hashed_password,
            "timeZone": time_zone,
            "traceId": trace_id,
            "userType": "1",
        }

        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "okhttp/3.14.9",
        }

        session = await self._get_session()
        try:
            async with session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                code = data.get("code")
                msg = data.get("msg", "")

                if code == 0 and "result" in data and data["result"]:
                    result = data["result"]
                    account_id = result.get("accountID") or result.get("accountId")
                    token = result.get("token")
                    if account_id and token:
                        return {
                            "account_id": str(account_id),
                            "token": str(token),
                            "source": "vesync",
                            "country_code": result.get("countryCode", "US"),
                            "time_zone": time_zone,
                        }
                elif code in (-11001, -11002, 11000):
                    raise PawsyncAuthError(f"Authentication failed: {msg} (code {code})")
                return None
        except asyncio.TimeoutError as err:
            raise PawsyncConnectionError("Timeout connecting to VeSync Cloud") from err
        except aiohttp.ClientError as err:
            raise PawsyncConnectionError(f"Network error connecting to VeSync: {err}") from err

    async def async_get_devices(
        self,
        account_id: str | None = None,
        token: str | None = None,
        country_code: str | None = None,
        time_zone: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch registered pet devices from Pawsync Cloud.
        Falls back to standard VeSync device list if needed.
        """
        acc_id = account_id or self.account_id
        tok = token or self.token
        country = country_code or self.country_code
        tz = time_zone or self.time_zone

        if not acc_id or not tok:
            raise PawsyncAuthError("Client is not authenticated. Call async_login first.")

        # Try 1: Pawsync pet device list
        try:
            devices = await self._async_get_pawsync_devices(acc_id, tok, country, tz)
            if devices is not None:
                return devices
        except Exception as err:
            _LOGGER.debug("Pawsync pet device query failed: %s", err)

        # Try 2: VeSync standard device list
        try:
            devices = await self._async_get_vesync_devices(acc_id, tok)
            if devices is not None:
                return devices
        except Exception as err:
            _LOGGER.error("VeSync device query failed: %s", err)

        return []

    async def _async_get_pawsync_devices(
        self,
        account_id: str,
        token: str,
        country_code: str,
        time_zone: str,
    ) -> list[dict[str, Any]] | None:
        """Query /pet/api/deviceManaged/v1/deviceList4Pet endpoint."""
        endpoint = f"{PAWSYNC_API_BASE}/pet/api/deviceManaged/v1/deviceList4Pet"
        trace_id = generate_trace_id()

        payload = {
            "context": {
                "traceId": trace_id,
                "method": "deviceList4Pet",
                "token": token,
                "accountID": account_id,
                "timeZone": time_zone,
                "userCountryCode": country_code,
                "acceptLanguage": "en",
                "debugMode": False,
                "osInfo": "Android 14",
                "clientType": "pawsync",
                "clientVersion": "1.1.32",
                "terminalId": hashlib.md5(account_id.encode("utf-8")).hexdigest(),
                "clientInfo": "pawsync",
                "appID": "psybfyca",
                "appVersion": "1.1.32",
                "phoneOS": "Android 14",
                "phoneBrand": "Android",
            },
            "data": {},
        }

        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "okhttp/3.14.9",
            "traceId": trace_id,
            "bizType": "pet",
            "accountID": account_id,
            "token": token,
        }

        session = await self._get_session()
        async with session.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if data.get("code") == 0 and "result" in data:
                raw_list = data["result"]
                if isinstance(raw_list, dict):
                    raw_list = raw_list.get("list", [])
                return self._normalize_devices(raw_list)
        return None

    async def _async_get_vesync_devices(
        self,
        account_id: str,
        token: str,
    ) -> list[dict[str, Any]] | None:
        """Query standard VeSync device list endpoint."""
        endpoint = f"{VESYNC_API_BASE}/cloud/v1/deviceManaged/devices"
        payload = {
            "acceptLanguage": "en",
            "accountID": account_id,
            "appVersion": "2.5.1",
            "method": "devices",
            "pageNo": "1",
            "pageSize": "100",
            "timeZone": self.time_zone,
            "token": token,
            "traceId": generate_trace_id(),
        }
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "okhttp/3.14.9",
        }

        session = await self._get_session()
        async with session.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if data.get("code") == 0 and "result" in data:
                res = data["result"]
                raw_list = res.get("list", []) if isinstance(res, dict) else res
                return self._normalize_devices(raw_list)
        return None

    def _normalize_devices(self, raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize device fields across Pawsync and VeSync schemas."""
        normalized = []
        for dev in raw_list:
            cid = dev.get("cid") or dev.get("deviceId") or dev.get("uuid") or ""
            prop = dev.get("deviceProp") if isinstance(dev.get("deviceProp"), dict) else {}

            # Extract MAC address from deviceProp or top-level fields
            raw_mac = (
                prop.get("wifiMac")
                or prop.get("mac")
                or prop.get("macID")
                or prop.get("macId")
                or dev.get("mac")
                or dev.get("macID")
                or dev.get("macId")
                or dev.get("deviceMac")
                or dev.get("wifiMac")
                or ""
            )

            # Format 12-char hex string as standard colon-delimited MAC (XX:XX:XX:XX:XX:XX)
            clean_mac = str(raw_mac).replace(":", "").replace("-", "").strip().upper()
            if len(clean_mac) == 12:
                formatted_mac = ":".join(clean_mac[i:i+2] for i in range(0, 12, 2))
            else:
                formatted_mac = str(raw_mac).strip().upper() if raw_mac else ""

            name = dev.get("deviceName") or dev.get("name") or "Pawsync Feeder"
            model = (
                dev.get("configModel")
                or dev.get("deviceModel")
                or dev.get("model")
                or dev.get("configModule")
                or prop.get("configModel")
                or prop.get("deviceModel")
                or ""
            )
            connection_status = (
                prop.get("connectionStatus")
                or dev.get("connectionStatus")
                or dev.get("deviceStatus")
                or "offline"
            )

            # Extract Wi-Fi SSID if present in device properties
            wifi_ssid = (
                prop.get("wifiName")
                or prop.get("wifiSsid")
                or prop.get("ssid")
                or dev.get("wifiName")
                or dev.get("wifiSsid")
                or dev.get("ssid")
                or ""
            )

            # Extract firmware version
            fw_version = ""
            for fw in prop.get("firmwareInfos", []):
                if isinstance(fw, dict) and (fw.get("isMainFw") or fw.get("type") == "mainFw"):
                    fw_version = fw.get("version", "")
                    break
            if not fw_version:
                fw_version = dev.get("currentFirmwareVersion") or prop.get("currentFirmwareVersion") or ""

            # Extract or resolve local IP address
            local_ip = (
                prop.get("localIp")
                or prop.get("ip")
                or prop.get("deviceIp")
                or prop.get("wifiIp")
                or dev.get("ip")
                or ""
            )
            if not local_ip and formatted_mac:
                local_ip = resolve_ip_from_mac(formatted_mac)

            # Check if this device is a feeder (matches PPF-R361S or general pet feeder)
            is_feeder = (
                "PPF-R361S" in model
                or "PFM" in model
                or "feeder" in name.lower()
                or "pawsync" in name.lower()
            )

            normalized.append({
                "cid": str(cid),
                "mac": formatted_mac,
                "ip": str(local_ip),
                "name": str(name),
                "model": str(model),
                "wifi_ssid": str(wifi_ssid),
                "sub_device_no": dev.get("subDeviceNo", 0),
                "status": str(connection_status),
                "is_feeder": is_feeder,
                "current_firmware_version": str(fw_version),
                "raw": dev,
            })
        return normalized

    async def async_harvest_feeder_profile(
        self,
        cid: str,
        account_id: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Harvest rich device configuration, portion calibration, and meal schedules."""
        acc_id = account_id or self.account_id or ""
        tok = token or self.token or ""
        trace_id = generate_trace_id()

        profile: dict[str, Any] = {
            "cid": cid,
            "harvested_at": int(time.time()),
            "single_weight_g": 10.0,
            "intelligent_feeding": False,
            "slow_feed": False,
            "sleep_mode": False,
            "bucket_surplus": 0,
            "plans": [],
            "raw_properties": {},
        }

        # 1. Fetch device properties via deviceList4Pet
        endpoint_dev = f"{PAWSYNC_API_BASE}/pet/api/deviceManaged/v1/deviceList4Pet"
        payload_dev = {
            "context": {
                "traceId": trace_id,
                "method": "deviceList4Pet",
                "token": tok,
                "accountID": acc_id,
                "timeZone": self.time_zone,
                "userCountryCode": self.country_code,
                "acceptLanguage": "en",
                "debugMode": False,
                "osInfo": "Android 14",
                "clientType": "pawsync",
                "clientVersion": "1.1.32",
                "terminalId": hashlib.md5(acc_id.encode("utf-8")).hexdigest() if acc_id else "",
                "clientInfo": "pawsync",
                "appID": "psybfyca",
                "appVersion": "1.1.32",
                "phoneOS": "Android 14",
                "phoneBrand": "Android",
            },
            "data": {},
        }
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "okhttp/3.14.9",
            "traceId": trace_id,
            "bizType": "pet",
            "accountID": acc_id,
            "token": tok,
        }

        session = await self._get_session()
        try:
            async with session.post(
                endpoint_dev,
                json=payload_dev,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 0 and "result" in data:
                        raw_list = data["result"]
                        if isinstance(raw_list, dict):
                            raw_list = raw_list.get("list", [])
                        for dev in raw_list:
                            dev_cid = dev.get("cid") or dev.get("deviceId") or dev.get("uuid") or ""
                            if dev_cid == cid or not cid:
                                prop = dev.get("deviceProp") if isinstance(dev.get("deviceProp"), dict) else {}
                                profile["raw_properties"] = prop
                                if "singleWeight_g" in prop:
                                    profile["single_weight_g"] = float(prop["singleWeight_g"])
                                if "intelligentFeedingSwitch" in prop:
                                    profile["intelligent_feeding"] = bool(prop["intelligentFeedingSwitch"])
                                if "slowFeedSwitch" in prop:
                                    profile["slow_feed"] = bool(prop["slowFeedSwitch"])
                                if "sleepMode" in prop:
                                    profile["sleep_mode"] = bool(prop["sleepMode"])
                                pet_food = prop.get("petFood") if isinstance(prop.get("petFood"), dict) else {}
                                if "bucketSurplus" in pet_food:
                                    profile["bucket_surplus"] = pet_food["bucketSurplus"]
                                break
        except Exception as err:
            _LOGGER.warning("Could not harvest device details for %s: %s", cid, err)

        # 2. Query getFeedingPlanList
        endpoint_plan_list = f"{PAWSYNC_API_BASE}/pet/api/deviceManaged/v1/getFeedingPlanList"
        payload_plan_list = {
            "context": {
                "traceId": generate_trace_id(),
                "method": "getFeedingPlanList",
                "token": tok,
                "accountID": acc_id,
                "timeZone": self.time_zone,
                "userCountryCode": self.country_code,
                "acceptLanguage": "en",
                "debugMode": False,
                "osInfo": "Android 14",
                "clientType": "pawsync",
                "clientVersion": "1.1.32",
                "terminalId": hashlib.md5(acc_id.encode("utf-8")).hexdigest() if acc_id else "",
                "clientInfo": "pawsync",
                "appID": "psybfyca",
                "appVersion": "1.1.32",
                "phoneOS": "Android 14",
                "phoneBrand": "Android",
            },
            "data": {"cid": cid, "subDeviceNo": 0},
        }

        plan_ids: list[Any] = []
        try:
            async with session.post(
                endpoint_plan_list,
                json=payload_plan_list,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 0 and "result" in data:
                        res = data["result"]
                        raw_plans = res.get("list", []) if isinstance(res, dict) else res
                        for p in raw_plans:
                            if isinstance(p, dict):
                                plan_id = p.get("planId") or p.get("id")
                                if plan_id:
                                    plan_ids.append(plan_id)
                                profile["plans"].append(p)
        except Exception as err:
            _LOGGER.warning("Could not harvest feeding plan list for %s: %s", cid, err)

        # 3. Query getFeedingPlanDetail for details if plans found
        for pid in plan_ids:
            endpoint_detail = f"{PAWSYNC_API_BASE}/pet/api/deviceManaged/v1/getFeedingPlanDetail"
            payload_detail = {
                "context": {
                    "traceId": generate_trace_id(),
                    "method": "getFeedingPlanDetail",
                    "token": tok,
                    "accountID": acc_id,
                    "timeZone": self.time_zone,
                    "userCountryCode": self.country_code,
                    "acceptLanguage": "en",
                    "debugMode": False,
                    "osInfo": "Android 14",
                    "clientType": "pawsync",
                    "clientVersion": "1.1.32",
                    "terminalId": hashlib.md5(acc_id.encode("utf-8")).hexdigest() if acc_id else "",
                    "clientInfo": "pawsync",
                    "appID": "psybfyca",
                    "appVersion": "1.1.32",
                    "phoneOS": "Android 14",
                    "phoneBrand": "Android",
                },
                "data": {"cid": cid, "planId": pid},
            }
            try:
                async with session.post(
                    endpoint_detail,
                    json=payload_detail,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == 0 and "result" in data:
                            detail = data["result"]
                            for existing_p in profile["plans"]:
                                if existing_p.get("planId") == pid or existing_p.get("id") == pid:
                                    existing_p["detail"] = detail
            except Exception as err:
                _LOGGER.warning("Could not harvest plan detail %s for %s: %s", pid, cid, err)

        _LOGGER.info(
            "Harvested cloud profile for %s: singleWeight_g=%.1f, %d plans",
            cid,
            profile["single_weight_g"],
            len(profile["plans"]),
        )
        return profile
