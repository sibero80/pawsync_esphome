#!/usr/bin/env python3
"""
tools/ota/get_vesync_credentials.py - Automated Pawsync & VeSync Credential & Device Extractor

Authenticates against smartapi.pawsync.com (native Pawsync app protocol with SHA-256)
and smartapi.vesync.com (standard VeSync app protocol with MD5) to extract:
  - Account ID
  - Session Token
  - Device CID (Client ID) & MAC Address for Pawsync PPF-R361S Feeder
"""

import sys
import time
import json
import uuid
import hashlib
import getpass
import argparse
from urllib import request, error

PAWSYNC_API_BASE = "https://smartapi.pawsync.com"
VESYNC_API_BASE = "https://smartapi.vesync.com"
TARGET_MODEL = "VS_WB_PFM_PPF-R361S-WUS_US"


def generate_trace_id() -> str:
    millis = int(time.time() * 1000)
    rand_suffix = str(uuid.uuid4()).replace("-", "")[:5]
    return f"PET{rand_suffix}{millis}-00001"


def login_pawsync_cloud(email: str, password: str, country_code: str = "US", time_zone: str = "America/New_York") -> dict | None:
    """Authenticates against the native Pawsync Pet App Cloud (smartapi.pawsync.com)."""
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
            "phoneBrand": "Android"
        },
        "data": {
            "email": email,
            "password": hashed_password
        }
    }

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": "okhttp/3.14.9",
        "traceId": trace_id,
        "bizType": "pet",
        "accountID": "",
        "token": ""
    }

    print(f"[*] Trying Pawsync App Cloud ({PAWSYNC_API_BASE})...")
    req = request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            code = data.get("code")
            msg = data.get("msg", "")

            if code == 0 and "result" in data and data["result"]:
                result = data["result"]
                account_id = result.get("accountId") or result.get("accountID")
                token = result.get("token")
                print(f"[+] SUCCESS: Logged in via Pawsync Cloud! (Account ID: {account_id})")
                return {
                    "account_id": account_id,
                    "token": token,
                    "source": "pawsync",
                    "country_code": result.get("countryCode", country_code),
                    "time_zone": result.get("timeZone", time_zone)
                }
            else:
                print(f"[-] Pawsync Cloud returned code {code}: {msg}")
                return None
    except error.HTTPError as e:
        err = e.read().decode("utf-8") if e.fp else str(e)
        print(f"[-] Pawsync Cloud HTTP {e.code}: {err}")
        return None
    except Exception as e:
        print(f"[-] Pawsync Cloud connection error: {e}")
        return None


def fetch_pawsync_devices(account_id: str, token: str, country_code: str = "US", time_zone: str = "America/New_York") -> list:
    """Fetch registered pet devices from Pawsync Cloud using deviceList4Pet."""
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
            "phoneBrand": "Android"
        },
        "data": {}
    }

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": "okhttp/3.14.9",
        "traceId": trace_id,
        "bizType": "pet",
        "accountID": account_id,
        "token": token
    }

    print("[*] Querying registered pet devices via deviceList4Pet...")
    req = request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0 and "result" in data:
                res = data["result"]
                if isinstance(res, dict):
                    return res.get("list", [])
                elif isinstance(res, list):
                    return res
    except Exception as e:
        print(f"[-] Failed to retrieve Pawsync device list: {e}")
    return []


def login_vesync_fallback(email: str, password: str, time_zone: str = "America/New_York") -> dict | None:
    """Fallback to VeSync App Cloud via pyvesync (smartapi.vesync.com with MD5)."""
    print(f"[*] Trying VeSync App Cloud fallback ({VESYNC_API_BASE})...")
    try:
        import asyncio
        from pyvesync import VeSync
        manager = VeSync(email, password, time_zone=time_zone)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(manager.login())
        if success:
            creds = manager.output_credentials_dict()
            account_id = creds.get("account_id")
            token = creds.get("token")
            print(f"[+] SUCCESS: Logged in via VeSync Cloud! (Account ID: {account_id})")
            return {
                "account_id": account_id,
                "token": token,
                "source": "vesync",
                "manager": manager
            }
        else:
            print("[-] VeSync Cloud login returned False.")
            return None
    except Exception as e:
        print(f"[-] VeSync Cloud fallback failed: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Pawsync & VeSync Credential & Device Extractor")
    parser.add_argument("--email", help="Account email")
    parser.add_argument("--password", help="Account password (prompted securely if omitted)")
    parser.add_argument("--country", default="US", help="Two-letter Country Code (default: US, e.g. CO, US, ES)")
    parser.add_argument("--tz", default="America/New_York", help="Timezone (default: America/New_York)")
    args = parser.parse_args()

    email = args.email
    if not email:
        email = input("Enter your Account Email: ").strip()

    password = args.password
    if not password:
        password = getpass.getpass("Enter your Account Password: ")

    # Attempt 1: Native Pawsync App Cloud (smartapi.pawsync.com)
    auth = login_pawsync_cloud(email, password, country_code=args.country, time_zone=args.tz)

    # If that failed and country was not CO, try with CO or specified
    if not auth and args.country == "US":
        print("[*] Retrying Pawsync Cloud with countryCode: CO...")
        auth = login_pawsync_cloud(email, password, country_code="CO", time_zone="America/Bogota")

    # Attempt 2: Fallback to standard VeSync Cloud
    if not auth:
        auth = login_vesync_fallback(email, password, time_zone=args.tz)

    if not auth:
        print("\n" + "=" * 65)
        print("[-] AUTHENTICATION FAILED ON BOTH PAWSYNC AND VESYNC CLOUD")
        print("=" * 65)
        print("Possible causes:")
        print("  1. Incorrect password.")
        print("  2. Account was registered under a different email or region.")
        print("  3. Account was created via Google Sign-In or Apple ID (which lacks a direct password).")
        print("\nAlternative: You can obtain your CID and Account ID directly from the app UI:")
        print("  - Open Pawsync/VeSync App -> Feeder -> Settings -> Device Info.")
        sys.exit(1)

    account_id = auth["account_id"]
    token = auth["token"]

    print("\n" + "=" * 65)
    print("AUTHENTICATION SUCCESSFUL")
    print("=" * 65)
    print(f"  Account ID : {account_id}")
    print(f"  Token      : {token}")
    print(f"  Auth Cloud : {auth.get('source', '').upper()}")
    print("=" * 65)

    # Fetch Devices
    feeders = []

    if auth.get("source") == "pawsync":
        devices = fetch_pawsync_devices(account_id, token, country_code=auth.get("country_code", "US"), time_zone=auth.get("time_zone", "America/New_York"))
        print(f"\n[*] Registered Devices Found ({len(devices)}):")
        for idx, d in enumerate(devices, 1):
            cid = d.get("deviceId") or d.get("cid")
            name = d.get("deviceName", "Unknown")
            dev_type = d.get("configModel") or d.get("deviceModel") or d.get("deviceType", "Unknown")
            prop = d.get("deviceProp") or {}
            mac = prop.get("wifiMac") or d.get("macID", "Unknown")
            status = prop.get("connectionStatus", "Unknown")
            wifi_ssid = prop.get("wifiName", "Unknown")
            main_fw = "Unknown"
            for fw in prop.get("firmwareInfos", []):
                if fw.get("isMainFw"):
                    main_fw = fw.get("version")
            print(f"  {idx}. Device: '{name}' | Model: {dev_type}")
            print(f"     CID: {cid} | MAC: {mac} | Wi-Fi: {wifi_ssid} | FW: {main_fw} | Status: {status}")
            if TARGET_MODEL in str(dev_type) or "feeder" in str(name).lower() or "r361" in str(dev_type).lower():
                feeders.append({
                    "name": name,
                    "cid": cid,
                    "mac": mac,
                    "wifi": wifi_ssid,
                    "fw": main_fw,
                    "status": status
                })
    else:
        # VeSync pyvesync manager
        try:
            import asyncio
            mgr = auth.get("manager")
            if mgr:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(mgr.get_devices())
                for idx, d in enumerate(mgr.devices or [], 1):
                    cid = getattr(d, "cid", None)
                    name = getattr(d, "device_name", "Unknown")
                    dev_type = getattr(d, "device_type", "Unknown")
                    mac = getattr(d, "mac_id", "Unknown")
                    print(f"  {idx}. Device: '{name}' | Type: {dev_type} | CID: {cid} | MAC: {mac}")
                    if TARGET_MODEL in str(dev_type) or "feeder" in str(name).lower():
                        feeders.append({
                            "name": name,
                            "cid": cid,
                            "mac": mac,
                            "wifi": "Unknown",
                            "fw": "Unknown",
                            "status": "Unknown"
                        })
        except Exception as e:
            print(f"[-] Device query error: {e}")

    print("\n" + "=" * 65)
    if feeders:
        print(f"[+] FOUND {len(feeders)} PAWSYNC PET FEEDER(S):")
        for i, f in enumerate(feeders, 1):
            print(f"  [{i}] {f['name']} (CID: {f['cid']}, MAC: {f['mac']}, Wi-Fi: {f['wifi']})")
    else:
        print("[-] Feeder CID was not auto-detected from device list.")
        print("    If a device is listed above, copy its CID.")
    print("=" * 65)

    cloud_host_arg = "--cloud-host smartapi.pawsync.com" if auth.get("source") == "pawsync" else ""
    
    print("\n>>> READY-TO-RUN FLASHING COMMANDS:")
    for i, f in enumerate(feeders, 1):
        print(f"\n--- Feeder #{i}: {f['name']} ({f['mac']}) ---")
        print(f"""/root/esphome/venv/bin/python3 tools/ota/trigger_ota.py --inject-cloud \\
  --account-id "{account_id}" \\
  --token "{token}" \\
  --cid "{f['cid']}" \\
  --url http://192.168.1.216:8000/pawsync_ota_update.bin {cloud_host_arg}""")


if __name__ == "__main__":
    main()
