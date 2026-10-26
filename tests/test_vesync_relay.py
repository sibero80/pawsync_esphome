"""Tests for VeSync / Pawsync Cloud Relay."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from custom_components.pawsync.vesync_relay import VeSyncRelay


@pytest.mark.asyncio
async def test_trigger_ota_payload():
    """Verify OTA trigger constructs bypassV2 envelope correctly."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"code": 0, "msg": "ok", "result": None})

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__.return_value = mock_resp

    relay = VeSyncRelay(
        account_id="acc_123",
        token="tok_abc",
        session=mock_session,
    )

    res = await relay.async_trigger_ota(
        cid="test_cid_001",
        download_url="http://192.168.1.140:8000/firmware.bin",
        model="VS_WB_PFM_PPF-R361S-WUS_US",
        version="9.9.9",
        url_mode="dword",
    )

    assert res["code"] == 0
    assert mock_session.post.called
    call_args = mock_session.post.call_args
    assert call_args is not None
    endpoint = call_args[0][0]
    assert "bypassV2" in endpoint

    payload = call_args[1]["json"]
    assert payload["accountID"] == "acc_123"
    assert payload["token"] == "tok_abc"
    assert payload["cid"] == "test_cid_001"
    assert payload["payload"]["method"] == "upFirmware"
    assert payload["payload"]["data"]["pluginName"] == "mainFw"
    assert "http://3232235916:8000/firmware.bin" in payload["payload"]["data"]["url"]
