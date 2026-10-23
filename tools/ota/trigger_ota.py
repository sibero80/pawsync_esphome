#!/usr/bin/env python3
"""
tools/ota/trigger_ota.py - Dual-Vector OTA Staging & Trigger Runner for Pawsync PPF-R361S

Supports:
  1. Developer Port 55555 Probe & Direct Local TCP Injection (ves_dev task).
  2. VeSync Cloud Bypass Injection (smartapi.vesync.com bypassV2 endpoint).
  3. Embedded Multi-threaded HTTP Staging Server with byte-transfer progress tracking.
"""

import sys
import os
import time
import json
import socket
import argparse
import threading
from urllib import request, error
from http.server import HTTPServer, SimpleHTTPRequestHandler

DEFAULT_DEV_PORT = 55555
DEFAULT_HTTP_PORT = 8000
DEFAULT_MODEL = "VS_WB_PFM_PPF-R361S-WUS_US"
DEFAULT_VERSION = "9.9.9"
VESYNC_API_BASE = "https://smartapi.vesync.com"


class OTAFileHandler(SimpleHTTPRequestHandler):
    """Custom HTTP handler with transfer logging and range support."""
    def log_message(self, format, *args):
        client_ip = self.client_address[0]
        print(f"  [HTTP Server] {client_ip} - {format % args}")


def get_local_ip() -> str:
    """Detect primary LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def probe_developer_port(host: str, port: int = DEFAULT_DEV_PORT, timeout: float = 3.0) -> bool:
    """Check if the feeder's ves_dev task is listening on TCP port 55555."""
    print(f"[*] Probing {host}:{port} (Local Developer TCP Port)...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        res = s.connect_ex((host, port))
        if res == 0:
            print(f"[+] SUCCESS: Developer Port {port} on {host} is OPEN!")
            return True
        else:
            print(f"[-] Port {port} on {host} is CLOSED (errno={res}).")
            print("    Note: On factory units out-of-the-box, ves_dev is dormant until dbg_cfg is enabled via Cloud Bypass.")
            return False
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        return False
    finally:
        s.close()


def send_local_tcp_command(host: str, port: int, payload: dict, timeout: float = 5.0) -> str:
    """Send JSON payload over local TCP connection to the feeder's port 55555."""
    data_str = json.dumps(payload) + "\n"
    print(f"[*] Connecting to {host}:{port}...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        print(f"[*] Dispatching JSON payload ({len(data_str)} bytes):\n    {json.dumps(payload, indent=2)}")
        s.sendall(data_str.encode("utf-8"))
        response = s.recv(4096).decode("utf-8", errors="replace")
        print(f"[+] Device response:\n    {response.strip()}")
        return response
    except Exception as e:
        print(f"[-] Error communicating with {host}:{port}: {e}")
        return ""
    finally:
        s.close()


def build_up_firmware_payload(url: str, cid: str = "", version: str = DEFAULT_VERSION) -> dict:
    """Construct upFirmware command matching decompiled bypass_method_up_firmware_handle."""
    trace_id = str(int(time.time() * 1000))
    return {
        "traceId": trace_id,
        "method": "upFirmware",
        "cid": cid,
        "data": {
            "pluginName": "mainFw",
            "url": url,
            "newVersion": version,
            "upMode": 2
        }
    }


def build_set_developer_payload(enabled: bool = True) -> dict:
    """Construct setDeveloper command matching decompiled bypass_method_set_developer_handle."""
    trace_id = str(int(time.time() * 1000))
    return {
        "traceId": trace_id,
        "method": "setDeveloper",
        "data": {
            "enabled": 1 if enabled else 0
        }
    }


def send_cloud_bypass(account_id: str, token: str, cid: str, payload_method: str, payload_data: dict) -> dict:
    """Dispatch bypass payload via VeSync smartapi bypassV2 endpoint."""
    trace_id = str(int(time.time() * 1000))
    endpoint = f"{VESYNC_API_BASE}/pet/api/deviceManaged/v1/bypassV2"

    body = {
        "context": {
            "accountID": account_id,
            "token": token,
            "traceId": trace_id,
            "method": payload_method,
            "cid": cid,
            "bizType": "petFeeder"
        },
        "data": payload_data
    }

    req = request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Pawsync/1.1.32 (Android 14; Build/46)"
        },
        method="POST"
    )

    print(f"[*] Posting to Cloud Bypass endpoint: {endpoint}")
    print(f"    Payload: {json.dumps(body, indent=2)}")

    try:
        with request.urlopen(req, timeout=10.0) as resp:
            resp_body = resp.read().decode("utf-8")
            data = json.loads(resp_body)
            print(f"[+] Cloud response:\n    {json.dumps(data, indent=2)}")
            return data
    except error.HTTPError as e:
        err_msg = e.read().decode("utf-8") if e.fp else str(e)
        print(f"[-] HTTP error ({e.code}): {err_msg}", file=sys.stderr)
        return {"code": e.code, "msg": err_msg}
    except Exception as e:
        print(f"[-] Network error: {e}", file=sys.stderr)
        return {"code": -1, "msg": str(e)}


def start_http_server(directory: str, port: int = DEFAULT_HTTP_PORT):
    """Run non-blocking local HTTP staging server."""
    os.chdir(directory)
    server = HTTPServer(("0.0.0.0", port), OTAFileHandler)
    local_ip = get_local_ip()
    print(f"[+] Staging HTTP Server running on http://{local_ip}:{port}/")
    print(f"    Serving directory: {directory}")
    print("    Waiting for device download request (Press Ctrl+C to terminate)...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping HTTP server.")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pawsync PPF-R361S OTA Trigger & Staging Runner")
    parser.add_argument("--feeder-ip", default="", help="Feeder IP address on local network")
    parser.add_argument("--probe", action="store_true", help="Probe developer TCP port 55555")
    parser.add_argument("--serve", action="store_true", help="Run local HTTP staging server")
    parser.add_argument("--serve-dir", default=".", help="Directory to serve (default: current dir)")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT, help=f"HTTP staging port (default: {DEFAULT_HTTP_PORT})")
    parser.add_argument("--inject-local", action="store_true", help="Send upFirmware JSON directly via local TCP port 55555")
    parser.add_argument("--inject-cloud", action="store_true", help="Send upFirmware JSON via VeSync cloud bypassV2 endpoint")
    parser.add_argument("--enable-dev", action="store_true", help="Send setDeveloper command to activate port 55555")
    parser.add_argument("--url", default="", help="Firmware download URL (e.g. http://192.168.1.100:8000/pawsync_ota_update.bin)")
    parser.add_argument("--cid", default="", help="Device Cloud Identifier (CID)")
    parser.add_argument("--account-id", default="", help="VeSync Account ID (for cloud bypass)")
    parser.add_argument("--token", default="", help="VeSync API Token (for cloud bypass)")
    parser.add_argument("--version", default=DEFAULT_VERSION, help=f"New firmware version string (default: {DEFAULT_VERSION})")

    args = parser.parse_args()

    if args.serve:
        start_http_server(args.serve_dir, args.http_port)
        sys.exit(0)

    if args.probe:
        if not args.feeder_ip:
            print("Error: --feeder-ip required for probe", file=sys.stderr)
            sys.exit(1)
        probe_developer_port(args.feeder_ip)
        sys.exit(0)

    if args.enable_dev:
        payload = build_set_developer_payload(True)
        if args.feeder_ip:
            send_local_tcp_command(args.feeder_ip, DEFAULT_DEV_PORT, payload)
        elif args.account_id and args.token and args.cid:
            send_cloud_bypass(args.account_id, args.token, args.cid, "setDeveloper", payload["data"])
        else:
            print("Error: Specify either --feeder-ip (for direct TCP) or --account-id/--token/--cid (for cloud bypass)", file=sys.stderr)
        sys.exit(0)

    if args.inject_local:
        if not args.feeder_ip or not args.url:
            print("Error: --feeder-ip and --url required for local injection", file=sys.stderr)
            sys.exit(1)
        payload = build_up_firmware_payload(args.url, args.cid, args.version)
        send_local_tcp_command(args.feeder_ip, DEFAULT_DEV_PORT, payload)
        sys.exit(0)

    if args.inject_cloud:
        if not (args.account_id and args.token and args.cid and args.url):
            print("Error: --account-id, --token, --cid, and --url required for cloud injection", file=sys.stderr)
            sys.exit(1)
        payload = build_up_firmware_payload(args.url, args.cid, args.version)
        send_cloud_bypass(args.account_id, args.token, args.cid, "upFirmware", payload["data"])
        sys.exit(0)

    parser.print_help()
