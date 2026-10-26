"""Tests for Pawsync Cloud API Client."""

import pytest
import aiohttp
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.pawsync.pawsync_api import (
    PawsyncApiClient,
    PawsyncAuthError,
    PawsyncConnectionError,
    generate_trace_id,
)


def test_generate_trace_id():
    """Verify trace ID format."""
    tid = generate_trace_id()
    assert tid.startswith("PET")
    assert tid.endswith("-00001")
    assert len(tid) >= 15


def test_normalize_devices():
    """Verify device normalization handles both Pawsync and VeSync fields."""
    client = PawsyncApiClient()
    raw_devices = [
        {
            "cid": "cid-12345",
            "deviceName": "Living Room Feeder",
            "deviceModel": "VS_WB_PFM_PPF-R361S-WUS_US",
            "connectionStatus": "online",
            "deviceProp": {
                "wifiMac": "1097bd4c18d8",
                "wifiName": "HomeWiFi",
            },
        },
        {
            "deviceId": "cid-67890",
            "deviceMac": "11:22:33:44:55:66",
            "name": "Cat Feeder 2",
            "model": "PPF-R361S",
            "deviceStatus": "offline",
        },
        {
            "cid": "plug-000",
            "mac": "99:88:77:66:55:44",
            "deviceName": "Smart Plug",
            "deviceModel": "ESW03-USA",
            "connectionStatus": "online",
        },
    ]

    normalized = client._normalize_devices(raw_devices)
    assert len(normalized) == 3

    dev1 = normalized[0]
    assert dev1["cid"] == "cid-12345"
    assert dev1["mac"] == "10:97:BD:4C:18:D8"
    assert dev1["name"] == "Living Room Feeder"
    assert dev1["wifi_ssid"] == "HomeWiFi"
    assert dev1["is_feeder"] is True
    assert dev1["status"] == "online"

    dev2 = normalized[1]
    assert dev2["cid"] == "cid-67890"
    assert dev2["mac"] == "11:22:33:44:55:66"
    assert dev2["name"] == "Cat Feeder 2"
    assert dev2["is_feeder"] is True
    assert dev2["status"] == "offline"

    dev3 = normalized[2]
    assert dev3["is_feeder"] is False


@pytest.mark.asyncio
async def test_async_login_pawsync_success():
    """Test successful login via Pawsync cloud."""
    mock_resp_json = {
        "code": 0,
        "msg": "ok",
        "result": {
            "accountId": "account_998877",
            "token": "token_secret_123",
            "countryCode": "US",
            "timeZone": "America/New_York",
        },
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_resp_json)

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__.return_value = mock_resp

    client = PawsyncApiClient(session=mock_session)
    auth = await client.async_login("user@example.com", "MyPassword123")

    assert auth["account_id"] == "account_998877"
    assert auth["token"] == "token_secret_123"
    assert auth["source"] == "pawsync"
    assert client.account_id == "account_998877"
    assert client.token == "token_secret_123"


@pytest.mark.asyncio
async def test_async_login_auth_error():
    """Test login failure raising PawsyncAuthError."""
    mock_resp_json = {
        "code": -11002,
        "msg": "password error",
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_resp_json)

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__.return_value = mock_resp

    client = PawsyncApiClient(session=mock_session)
    with pytest.raises(PawsyncAuthError):
        await client.async_login("user@example.com", "WrongPassword")
