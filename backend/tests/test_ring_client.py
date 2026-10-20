import pytest
import httpx

from countersign.ring_client import (
    RingClient,
    RingClientError,
    RingDeviceInaccessibleError,
    RingTokenExpiredError,
)


@pytest.fixture
def mock_devices_doc():
    return {
        "data": [
            {
                "id": "doorbell-encrypted",
                "type": "device",
                "attributes": {
                    "description": "Encrypted Doorbell",
                    "kind": "doorbell",
                    "configuration": {"e2e_encryption": {"enabled": True}},
                    "status": {"online": True},
                },
            },
            {
                "id": "doorbell-offline",
                "type": "device",
                "attributes": {
                    "description": "Offline Doorbell",
                    "kind": "doorbell",
                    "configuration": {"e2e_encryption": {"enabled": False}},
                    "status": {"online": False},
                },
            },
            {
                "id": "doorbell-active",
                "type": "device",
                "attributes": {
                    "description": "Front Door",
                    "kind": "doorbell",
                    "configuration": {"e2e_encryption": {"enabled": False}},
                    "status": {"online": True},
                },
            },
        ]
    }


@pytest.mark.asyncio
async def test_find_door_device_filters_encrypted_and_offline(mock_devices_doc):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json=mock_devices_doc)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RingClient(token="test-token", http_client=http)
        device = await client.find_door_device()
        assert device["id"] == "doorbell-active"
        assert device["attributes"]["description"] == "Front Door"


@pytest.mark.asyncio
async def test_find_door_device_specific_id(mock_devices_doc):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_devices_doc)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RingClient(token="test-token", http_client=http)
        # Choosing the encrypted device explicitly should fail with inaccessible error
        with pytest.raises(RingDeviceInaccessibleError):
            await client.find_door_device(preferred_device_id="doorbell-encrypted")


@pytest.mark.asyncio
async def test_token_expiry_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "token_expired"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RingClient(token="expired-token", http_client=http)
        with pytest.raises(RingTokenExpiredError):
            await client.list_devices()


@pytest.mark.asyncio
async def test_device_offline_503():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "device_unavailable"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RingClient(token="test-token", http_client=http)
        with pytest.raises(RingDeviceInaccessibleError):
            await client.start_whep("dev-1", "v=0\r\no=- 0 0 IN IP4 127.0.0.1")


@pytest.mark.asyncio
async def test_whep_lifecycle():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and "whep/sessions" in str(request.url):
            assert request.headers["Content-Type"] == "application/sdp"
            return httpx.Response(
                201,
                text="v=0\r\no=server 0 0 IN IP4 127.0.0.1\r\ns=WHEP Answer",
                headers={"Location": "https://api.amazonvision.com/v1/devices/dev-1/media/streaming/whep/sessions/sess-123"},
            )
        if request.method == "DELETE" and "sess-123" in str(request.url):
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RingClient(token="test-token", http_client=http)
        answer_sdp, location = await client.start_whep("dev-1", "offer-sdp")
        assert "WHEP Answer" in answer_sdp
        assert location and "sess-123" in location

        # Stop session
        await client.stop_whep("dev-1", location)


def test_missing_token_raises():
    client = RingClient(token="")
    with pytest.raises(RingClientError):
        client._get_headers()
