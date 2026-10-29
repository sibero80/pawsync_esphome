"""Tests for dynamic in-memory firmware patcher."""

import struct
import pytest

from custom_components.pawsync.firmware_patcher import (
    SSID_PLACEHOLDER,
    PASS_PLACEHOLDER,
    NOISE_PSK_PLACEHOLDER,
    OTA_PASSWORD_PLACEHOLDER,
    MAX_SSID_LEN,
    MAX_PASS_LEN,
    MAX_NOISE_PSK_LEN,
    MAX_OTA_PASS_LEN,
    FirmwarePatchError,
    generate_noise_psk,
    generate_ota_password,
    safe_truncate_utf8,
    can_patch_firmware,
    patch_raw_esp32_credentials,
    package_vesync_ota_container,
    patch_container_firmware,
    prepare_customized_firmware_file,
    recalculate_esp32_checksum,
    recalculate_esp32_sha256,
    validate_esp32_image_structure,
)
from tests.fixtures.synthetic_firmware import create_synthetic_esp32_binary


def test_safe_truncate_utf8_ascii():
    """Verify safe truncation on standard ASCII strings."""
    # Under limit
    res = safe_truncate_utf8("MyWifi", 31)
    assert len(res) == 32
    assert res.startswith(b"MyWifi\x00")

    # Exact limit (31 chars)
    exact_31 = "A" * 31
    res = safe_truncate_utf8(exact_31, 31)
    assert len(res) == 32
    assert res == exact_31.encode("ascii") + b"\x00"

    # Exceeding limit (40 chars)
    over_40 = "B" * 40
    res = safe_truncate_utf8(over_40, 31)
    assert len(res) == 32
    assert res == ("B" * 31).encode("ascii") + b"\x00"

    # Empty string
    assert safe_truncate_utf8("", 31) == b"\x00" * 32


def test_safe_truncate_utf8_multibyte():
    """Verify safe truncation preserves multi-byte UTF-8 boundaries without splitting."""
    # "Café" is 5 bytes (C-a-f-\xc3\xa9)
    res = safe_truncate_utf8("Café", 31)
    assert len(res) == 32
    assert res.startswith("Café".encode("utf-8") + b"\x00")

    # Multi-byte emoji at boundary: 29 'A's (29 bytes) + '⚡' (3 bytes) = 32 bytes (>31)
    # Truncation must drop the entire '⚡' and not leave 2 invalid leading bytes
    text = ("A" * 29) + "⚡"
    res = safe_truncate_utf8(text, 31)
    assert len(res) == 32
    # Should only contain 29 'A's followed by 3 null terminators
    assert res == ("A" * 29).encode("ascii") + b"\x00\x00\x00"


def test_can_patch_firmware_detection():
    """Verify detection of patchable firmware."""
    fake_raw = b"\x00" * 100 + SSID_PLACEHOLDER + b"\x00" * 50 + PASS_PLACEHOLDER + b"\x00" * 100
    assert can_patch_firmware(fake_raw) is True

    fake_container = bytes([0x01]) + b"\x00" * 128 + fake_raw
    assert can_patch_firmware(fake_container) is True

    assert can_patch_firmware(b"\x00" * 300) is False


def test_patch_raw_credentials_fail_closed():
    """Verify patch_raw_esp32_credentials raises FirmwarePatchError when placeholders missing."""
    raw_no_placeholders = create_synthetic_esp32_binary(include_placeholders=False)
    with pytest.raises(FirmwarePatchError, match="Required Wi-Fi placeholders not found"):
        patch_raw_esp32_credentials(raw_no_placeholders, "MySSID", "MyPassword")


def test_prepare_customized_firmware_fail_closed(tmp_path):
    """Verify prepare_customized_firmware_file fails closed on unpatchable or missing images."""
    # Non-existent file
    with pytest.raises(FirmwarePatchError, match="not found"):
        prepare_customized_firmware_file(
            str(tmp_path / "nonexistent.bin"),
            str(tmp_path),
            "MySSID",
            "MyPassword",
        )

    # File without placeholders
    bad_file = tmp_path / "bad.bin"
    bad_file.write_bytes(create_synthetic_esp32_binary(include_placeholders=False))
    with pytest.raises(FirmwarePatchError, match="Required.*placeholders not found"):
        prepare_customized_firmware_file(
            str(bad_file),
            str(tmp_path),
            "MySSID",
            "MyPassword",
        )


def test_patch_container_firmware_end_to_end(tmp_path):
    """Verify end-to-end container patching with synthetic valid binary."""
    raw_bin = create_synthetic_esp32_binary(include_placeholders=True)
    orig_container = package_vesync_ota_container(raw_bin)

    assert can_patch_firmware(orig_container) is True

    patched = patch_container_firmware(
        orig_container,
        ssid="MyLivingRoomWifi",
        password="SuperSecurePassword123!",
    )

    assert len(patched) == len(orig_container)
    assert b"MyLivingRoomWifi" in patched
    assert b"SuperSecurePassword123!" in patched
    assert SSID_PLACEHOLDER not in patched
    assert PASS_PLACEHOLDER not in patched

    # Check VeSync container header byte
    assert patched[0] == 0x01
    # Check ESP32 magic byte
    assert patched[129] == 0xE9


def test_patch_noise_psk_and_ota_password_end_to_end():
    """Verify dynamic byte patching of Noise PSK and OTA password (Sprint 2)."""
    raw_bin = create_synthetic_esp32_binary(
        include_placeholders=True,
        include_psk=True,
        include_ota=True,
    )
    orig_container = package_vesync_ota_container(raw_bin)

    assert can_patch_firmware(orig_container, require_psk=True, require_ota=True) is True

    psk = generate_noise_psk()
    ota_pw = generate_ota_password(16)
    assert len(psk.encode("ascii")) == 44
    assert len(ota_pw) == 16

    patched = patch_container_firmware(
        orig_container,
        ssid="SmartFeederNet",
        password="FeederSecretPass!",
        noise_psk=psk,
        ota_password=ota_pw,
    )

    assert len(patched) == len(orig_container)
    assert b"SmartFeederNet" in patched
    assert b"FeederSecretPass!" in patched
    assert psk.encode("ascii") in patched
    assert ota_pw.encode("ascii") in patched

    assert SSID_PLACEHOLDER not in patched
    assert PASS_PLACEHOLDER not in patched
    assert NOISE_PSK_PLACEHOLDER not in patched
    assert OTA_PASSWORD_PLACEHOLDER not in patched


def test_patch_noise_psk_invalid_length_fails_closed():
    """Verify invalid Noise PSK length raises FirmwarePatchError."""
    raw_bin = create_synthetic_esp32_binary(
        include_placeholders=True,
        include_psk=True,
    )
    with pytest.raises(FirmwarePatchError, match="Noise PSK length invalid"):
        patch_raw_esp32_credentials(
            raw_bin,
            ssid="MySSID",
            password="MyPassword",
            noise_psk="TOO_SHORT_PSK",
        )


def test_missing_noise_psk_placeholder_fails_closed():
    """Verify missing Noise PSK placeholder raises FirmwarePatchError when PSK requested."""
    raw_bin_no_psk = create_synthetic_esp32_binary(
        include_placeholders=True,
        include_psk=False,
    )
    valid_psk = generate_noise_psk()
    with pytest.raises(FirmwarePatchError, match="Required Noise PSK placeholder not found"):
        patch_raw_esp32_credentials(
            raw_bin_no_psk,
            ssid="MySSID",
            password="MyPassword",
            noise_psk=valid_psk,
        )


def test_missing_ota_placeholder_fails_closed():
    """Verify missing OTA placeholder raises FirmwarePatchError when OTA password requested."""
    raw_bin_no_ota = create_synthetic_esp32_binary(
        include_placeholders=True,
        include_ota=False,
    )
    with pytest.raises(FirmwarePatchError, match="Required OTA password placeholder not found"):
        patch_raw_esp32_credentials(
            raw_bin_no_ota,
            ssid="MySSID",
            password="MyPassword",
            ota_password="SecureOtaPassword123",
        )


def test_validate_esp32_image_structure_valid():
    """Verify structurally valid binary passes validation."""
    valid_bin = create_synthetic_esp32_binary(include_placeholders=False)
    assert validate_esp32_image_structure(valid_bin, require_no_placeholders=True) is True


def test_validate_esp32_image_structure_corruptions():
    """Verify structural validator rejects invalid magic, segment count, and truncated headers."""
    valid_bin = bytearray(create_synthetic_esp32_binary(include_placeholders=False))

    # 1. Payload too small
    with pytest.raises(FirmwarePatchError, match="Firmware payload too small"):
        validate_esp32_image_structure(b"\x00" * 100)

    # 2. Invalid magic byte (not 0xE9)
    bad_magic = bytearray(valid_bin)
    bad_magic[0] = 0xAA
    with pytest.raises(FirmwarePatchError, match="Invalid ESP32 image magic byte"):
        validate_esp32_image_structure(bytes(bad_magic))

    # 3. Invalid segment count (0 or 20)
    bad_seg = bytearray(valid_bin)
    bad_seg[1] = 0
    with pytest.raises(FirmwarePatchError, match="Invalid ESP32 segment count"):
        validate_esp32_image_structure(bytes(bad_seg))

    bad_seg[1] = 20
    with pytest.raises(FirmwarePatchError, match="Invalid ESP32 segment count"):
        validate_esp32_image_structure(bytes(bad_seg))

    # 4. Corrupted segment length exceeding binary size
    corrupt_len = bytearray(valid_bin)
    # segment 0 length is at offset 28..31
    struct.pack_into("<I", corrupt_len, 28, 9999999)
    with pytest.raises(FirmwarePatchError, match="exceeds total binary size"):
        validate_esp32_image_structure(bytes(corrupt_len))


def test_validate_esp32_image_structure_rejects_leftover_placeholders():
    """Verify placeholder presence detection raises FirmwarePatchError."""
    bin_with_placeholders = create_synthetic_esp32_binary(include_placeholders=True, include_psk=True)
    with pytest.raises(FirmwarePatchError, match="unpatched placeholder.*found in binary"):
        validate_esp32_image_structure(bin_with_placeholders, require_no_placeholders=True)


def test_patch_compiled_noise_psk_binary():
    """Verify dynamic byte patching works when firmware has compiled 32-byte Noise PSK instead of ASCII placeholder."""
    from custom_components.pawsync.firmware_patcher import (
        DEFAULT_COMPILED_NOISE_PSK_BYTES,
        NOISE_PSK_PLACEHOLDER,
    )
    import base64

    # Create synthetic binary and replace ASCII placeholder with 32-byte compiled key
    raw_bin = create_synthetic_esp32_binary(include_placeholders=True, include_psk=True, include_ota=True)
    raw_bin = raw_bin.replace(NOISE_PSK_PLACEHOLDER, DEFAULT_COMPILED_NOISE_PSK_BYTES.ljust(44, b"\x00"))

    assert can_patch_firmware(raw_bin, require_psk=True, require_ota=True) is True

    new_psk = generate_noise_psk()
    new_psk_raw = base64.b64decode(new_psk)

    patched = patch_raw_esp32_credentials(
        raw_bin,
        ssid="MyWifiNet",
        password="MySecretPassword123",
        noise_psk=new_psk,
        ota_password="SecureOtaPassword123",
    )

    assert new_psk_raw in patched
    assert DEFAULT_COMPILED_NOISE_PSK_BYTES not in patched
    assert b"MyWifiNet" in patched

