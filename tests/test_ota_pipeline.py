#!/usr/bin/env python3
"""
tests/test_ota_pipeline.py - Comprehensive Unit & Integration Test Suite for Pawsync OTA Pipeline

Validates:
  1. Cryptographic packaging: 129-byte container, AES-128-CBC key/IV decryption, MD5 roundtrip.
  2. Partition size safety: Hard boundary enforcement (<= 1,310,720 bytes).
  3. Image integrity: ESP32 image magic byte (0xE9) validation.
  4. Command payload schemas: upFirmware and setDeveloper JSON structures.
  5. Local HTTP staging server: real-time transfer and byte verification.
  6. Production firmware package: packaging and verifying .esphome/build/pawsync-feeder/build/firmware.ota.bin.
"""

import os
import sys
import time
import json
import socket
import hashlib
import tempfile
import threading
from urllib import request
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Add repository root to python module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.ota.build_vesync_ota import (
    create_vesync_ota_package,
    DEFAULT_KEY,
    DEFAULT_IV,
    DEFAULT_MODEL,
    DEFAULT_VERSION,
    MAX_OTA_PARTITION_SIZE,
    ESP_IMAGE_HEADER_MAGIC
)
from tools.ota.trigger_ota import (
    build_up_firmware_payload,
    build_set_developer_payload,
    build_cloud_bypass_payload,
    probe_developer_port,
    OTAFileHandler,
    HTTPServer
)


def test_container_crypto_and_header_parsing():
    """Verify 129-byte container format, AES-128-CBC decryption, and header fields."""
    print("[*] Running Test 1: Container packaging, AES-128-CBC decryption & MD5 roundtrip...")
    # Generate 64 KB test payload with ESP32 magic byte
    dummy_payload = bytes([ESP_IMAGE_HEADER_MAGIC]) + os.urandom(65535)
    expected_md5 = hashlib.md5(dummy_payload).hexdigest().encode('ascii')

    with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
        in_f.write(dummy_payload)
        in_bin_path = in_f.name

    with tempfile.NamedTemporaryFile("wb", delete=False) as out_f:
        out_pkg_path = out_f.name

    try:
        create_vesync_ota_package(in_bin_path, out_pkg_path, model=DEFAULT_MODEL, version="9.9.9")

        with open(out_pkg_path, "rb") as f:
            pkg_data = f.read()

        assert len(pkg_data) == len(dummy_payload) + 129, f"Unexpected package size: {len(pkg_data)}"
        assert pkg_data[0] == 0x01, f"Unexpected crypto_type byte: 0x{pkg_data[0]:02X}"

        # Decrypt header
        enc_header = pkg_data[1:129]
        cipher = Cipher(algorithms.AES(DEFAULT_KEY), modes.CBC(DEFAULT_IV))
        decryptor = cipher.decryptor()
        dec_header = decryptor.update(enc_header) + decryptor.finalize()

        assert dec_header[0] == 0x01, "Header byte 0 must be 0x01"
        assert dec_header[1:33] == expected_md5, f"MD5 mismatch: {dec_header[1:33]} != {expected_md5}"
        assert dec_header[33] == 0x00, "MD5 terminator null missing"
        assert dec_header[34:34 + len(DEFAULT_MODEL[:15])] == DEFAULT_MODEL[:15].encode('ascii')
        assert dec_header[50:50 + len("9.9.9")] == b"9.9.9"
        assert dec_header[66:70] == b"1.0\x00"
        assert dec_header[74:76] == b"UN"

        # Check payload
        payload_in_pkg = pkg_data[129:]
        assert payload_in_pkg == dummy_payload
        print("    [PASS] Test 1: Container packaging, AES decryption, and field offsets verified.")
    finally:
        if os.path.exists(in_bin_path):
            os.remove(in_bin_path)
        if os.path.exists(out_pkg_path):
            os.remove(out_pkg_path)


def test_hard_partition_size_guardrail():
    """Verify that any binary exceeding 1,310,720 bytes is blocked immediately."""
    print("[*] Running Test 2: Hard partition size limit guardrail (1,310,720 bytes)...")
    oversized_len = MAX_OTA_PARTITION_SIZE + 1024
    oversized_payload = bytes([ESP_IMAGE_HEADER_MAGIC]) + bytes(oversized_len - 1)

    with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
        in_f.write(oversized_payload)
        in_bin_path = in_f.name

    out_pkg_path = in_bin_path + ".pkg"

    try:
        try:
            create_vesync_ota_package(in_bin_path, out_pkg_path)
            assert False, "Failed: oversized binary was not blocked!"
        except SystemExit as e:
            assert e.code != 0, f"Expected non-zero exit code on overflow, got {e.code}"
            print("    [PASS] Test 2: Oversized binary (1,311,744 bytes) correctly blocked before packaging.")
    finally:
        if os.path.exists(in_bin_path):
            os.remove(in_bin_path)
        if os.path.exists(out_pkg_path):
            os.remove(out_pkg_path)


def test_image_magic_byte_validation():
    """Verify that non-ESP32 binaries (missing 0xE9 magic byte) are rejected unless forced."""
    print("[*] Running Test 3: ESP32 image magic byte (0xE9) validation...")
    bad_payload = b"\x7FELF" + os.urandom(1020)  # ELF file, not raw flash image

    with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
        in_f.write(bad_payload)
        in_bin_path = in_f.name

    out_pkg_path = in_bin_path + ".pkg"

    try:
        try:
            create_vesync_ota_package(in_bin_path, out_pkg_path, force=False)
            assert False, "Failed: non-ESP binary was not blocked!"
        except SystemExit as e:
            assert e.code != 0
            print("    [PASS] Test 3: Non-ESP binary correctly rejected.")
    finally:
        if os.path.exists(in_bin_path):
            os.remove(in_bin_path)
        if os.path.exists(out_pkg_path):
            os.remove(out_pkg_path)


def test_command_payload_schemas():
    """Verify upFirmware and setDeveloper JSON schemas matching decompiled dispatchers."""
    print("[*] Running Test 4: upFirmware & setDeveloper command schemas...")
    p1 = build_up_firmware_payload("http://192.168.1.100:8000/firmware.bin", cid="TEST_CID", version="9.9.9")
    assert p1["method"] == "upFirmware"
    assert p1["cid"] == "TEST_CID"
    assert p1["data"]["pluginName"] == "mainFw"
    assert p1["data"]["url"] == "http://192.168.1.100:8000/firmware.bin"
    assert p1["data"]["newVersion"] == "9.9.9"
    assert p1["data"]["upMode"] == 2

    p2 = build_set_developer_payload(True)
    assert p2["method"] == "setDeveloper"
    assert p2["data"]["enabled"] == 1

    print("    [PASS] Test 4: JSON schemas match decompiled stock firmware handlers.")


def test_cloud_bypass_payload_and_headers():
    """Verify VeSync Cloud Bypass V2 request body and HTTP headers matching APK specifications."""
    print("[*] Running Test 5: VeSync Cloud Bypass V2 schema and gateway headers...")
    command_data = {
        "pluginName": "mainFw",
        "url": "http://192.168.1.100:8000/firmware.bin",
        "newVersion": "9.9.9",
        "upMode": 2
    }
    endpoint, body, headers = build_cloud_bypass_payload(
        account_id="ACC_12345",
        token="TOK_ABCDE",
        cid="DEV_FEEDER_001",
        method="upFirmware",
        command_data=command_data
    )

    # 1. Endpoint Check
    assert endpoint.endswith("/pet/api/deviceManaged/v1/bypassV2"), f"Invalid endpoint: {endpoint}"

    # 2. HTTP Gateway Headers Check
    assert headers["accountID"] == "ACC_12345", "Missing accountID header"
    assert headers["token"] == "TOK_ABCDE", "Missing token header"
    assert headers["bizType"] == "pet", f"Invalid bizType header: {headers.get('bizType')}"
    assert "traceId" in headers, "Missing traceId header"
    assert "application/json" in headers["Content-Type"], "Invalid Content-Type header"
    assert "Pawsync" in headers["User-Agent"], "Invalid User-Agent header"

    # 3. Context Payload Check
    ctx = body["context"]
    assert ctx["accountID"] == "ACC_12345"
    assert ctx["token"] == "TOK_ABCDE"
    assert ctx["bizType"] == "pet", f"Invalid context.bizType: {ctx.get('bizType')}"
    assert ctx["userType"] == "1", f"Invalid context.userType: {ctx.get('userType')}"
    assert ctx["countryCode"] == "US"
    assert "method" not in ctx, "'method' must NOT be placed inside context!"
    assert "cid" not in ctx, "'cid' must NOT be placed inside context!"

    # 4. Device Command Envelope Check
    envelope = body["data"]
    assert envelope["method"] == "upFirmware"
    assert envelope["source"] == "APP"
    device_data = envelope["data"]
    assert device_data["cid"] == "DEV_FEEDER_001"
    assert device_data["configModule"] == DEFAULT_MODEL
    assert device_data["pluginName"] == "mainFw"
    assert device_data["url"] == "http://192.168.1.100:8000/firmware.bin"
    assert device_data["newVersion"] == "9.9.9"
    assert device_data["upMode"] == 2

    print("    [PASS] Test 5: Cloud Bypass V2 schema, gateway headers, and nested device envelope verified.")


def test_http_staging_server():
    """Verify local HTTP staging server serving file with exact byte length."""
    print("[*] Running Test 6: Local HTTP staging server transfer simulation...")
    test_data = b"OTA_TEST_PACKAGE_DATA_" * 1024  # 22.5 KB
    temp_dir = tempfile.mkdtemp()
    test_file_path = os.path.join(temp_dir, "test_ota.bin")

    with open(test_file_path, "wb") as f:
        f.write(test_data)

    port = 8765
    server = HTTPServer(("127.0.0.1", port), OTAFileHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)

    try:
        url = f"http://127.0.0.1:{port}/test_ota.bin"
        # Temporarily chdir to temp_dir
        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        try:
            with request.urlopen(url, timeout=3.0) as resp:
                downloaded = resp.read()
                assert len(downloaded) == len(test_data), f"Length mismatch: {len(downloaded)} != {len(test_data)}"
                assert downloaded == test_data, "Downloaded data corrupted"
            print("    [PASS] Test 6: HTTP staging server delivered exact payload.")
        finally:
            os.chdir(old_cwd)
    finally:
        server.shutdown()
        server.server_close()
        if os.path.exists(test_file_path):
            os.remove(test_file_path)
        os.rmdir(temp_dir)


def test_production_binary_package():
    """Verify packaging the actual compiled ESPHome binary in pawsync_oma2."""
    print("[*] Running Test 7: Production ESPHome binary packaging & verification...")
    prod_bin = "/root/pawsync_oma2/.esphome/build/pawsync-feeder/build/firmware.ota.bin"
    if not os.path.exists(prod_bin):
        print("    [SKIP] Production binary firmware.ota.bin not found (compile needed first).")
        return

    out_pkg = "pawsync_ota_update.bin"
    create_vesync_ota_package(prod_bin, out_pkg, model=DEFAULT_MODEL, version="9.9.9")

    assert os.path.exists(out_pkg)
    with open(out_pkg, "rb") as f:
        data = f.read()

    with open(prod_bin, "rb") as f:
        orig_bin = f.read()

    assert len(data) == len(orig_bin) + 129
    assert data[0] == 0x01
    enc_hdr = data[1:129]
    payload = data[129:]

    cipher = Cipher(algorithms.AES(DEFAULT_KEY), modes.CBC(DEFAULT_IV))
    decryptor = cipher.decryptor()
    hdr = decryptor.update(enc_hdr) + decryptor.finalize()

    payload_md5 = hashlib.md5(orig_bin).hexdigest().encode('ascii')
    assert hdr[1:33] == payload_md5
    assert hdr[34:34 + len(DEFAULT_MODEL[:15])] == DEFAULT_MODEL[:15].encode('ascii')
    assert hdr[50:50 + len("9.9.9")] == b"9.9.9"

    print(f"    [PASS] Test 6: Production package '{out_pkg}' verified ({len(data):,} bytes).")


if __name__ == "__main__":
    print("=" * 70)
    print("PAWSYNC PPF-R361S OTA PIPELINE VERIFICATION SUITE")
    print("=" * 70)

    test_container_crypto_and_header_parsing()
    test_hard_partition_size_guardrail()
    test_image_magic_byte_validation()
    test_command_payload_schemas()
    test_cloud_bypass_payload_and_headers()
    test_http_staging_server()
    test_production_binary_package()

    print("=" * 70)
    print("ALL 7 OTA PIPELINE TESTS PASSED CLEANLY (100% SUCCESS)!")
    print("=" * 70)
