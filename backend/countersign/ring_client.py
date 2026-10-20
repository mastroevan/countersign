"""Ring Partner API (Amazon Vision API) client.

Handles device discovery, end-to-end encryption checks, and WHEP live-view
session management over https://api.amazonvision.com.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_AVA_BASE_URL = "https://api.amazonvision.com"
DEFAULT_RING_TOKEN_ENV = "RING_ACCESS_TOKEN"
DEFAULT_RING_DOOR_DEVICE_ID_ENV = "RING_DOOR_DEVICE_ID"


class RingClientError(RuntimeError):
    """Base error for Ring API interactions."""


class RingTokenExpiredError(RingClientError):
    """The 30-minute Ring Playground token has expired (HTTP 401)."""


class RingDeviceInaccessibleError(RingClientError):
    """The device is offline, encrypted, or cannot be streamed."""


class RingClient:
    """Client for the Amazon Vision API / Ring Partner API."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token or os.environ.get(DEFAULT_RING_TOKEN_ENV, "")
        self.base_url = (base_url or os.environ.get("RING_API_BASE_URL") or DEFAULT_AVA_BASE_URL).rstrip("/")
        self._http = http_client

    def _get_headers(self, token: str | None = None, content_type: str | None = None) -> dict[str, str]:
        t = token or self.token
        if not t:
            raise RingClientError(
                f"Ring access token missing. Set {DEFAULT_RING_TOKEN_ENV} or pass token."
            )
        headers = {"Authorization": f"Bearer {t}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _check_response_status(self, response: httpx.Response, action_description: str) -> None:
        if response.status_code == 401:
            raise RingTokenExpiredError(
                f"Ring token expired during {action_description}. Re-authenticate in Ring Playground."
            )
        if response.status_code == 503:
            raise RingDeviceInaccessibleError(
                f"Ring device temporarily unavailable (HTTP 503) during {action_description}."
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RingClientError(
                f"Ring API error ({response.status_code}) during {action_description}: {response.text}"
            ) from exc

    async def list_devices(
        self,
        token: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """List devices with status, capabilities, and configurations (JSON:API)."""
        client = http or self._http
        headers = self._get_headers(token)
        url = f"{self.base_url}/v1/devices"
        params = {"include": "status,capabilities,configurations"}

        if client is not None:
            r = await client.get(url, params=params, headers=headers)
            self._check_response_status(r, "list_devices")
            return r.json()  # type: ignore[no-any-return]

        async with httpx.AsyncClient() as session:
            r = await session.get(url, params=params, headers=headers)
            self._check_response_status(r, "list_devices")
            return r.json()  # type: ignore[no-any-return]

    async def find_door_device(
        self,
        token: str | None = None,
        preferred_device_id: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Find an accessible door camera device. Skips encrypted and offline devices."""
        device_id = preferred_device_id or os.environ.get(DEFAULT_RING_DOOR_DEVICE_ID_ENV)
        doc = await self.list_devices(token=token, http=http)

        # Build lookup tables from included objects if JSON:API
        included_confs: dict[str, dict[str, Any]] = {}
        included_statuses: dict[str, dict[str, Any]] = {}
        for inc in doc.get("included", []):
            inc_type = inc.get("type")
            inc_id = inc.get("id")
            if inc_type == "configuration":
                included_confs[inc_id] = inc.get("attributes", {})
            elif inc_type == "status":
                included_statuses[inc_id] = inc.get("attributes", {})

        devices = doc.get("data", [])
        if isinstance(doc, list):
            devices = doc

        if not devices:
            raise RingDeviceInaccessibleError("No Ring devices found on account.")

        selected: dict[str, Any] | None = None
        for dev in devices:
            d_id = str(dev.get("id"))
            if device_id and d_id != str(device_id):
                continue

            attrs = dev.get("attributes", {})
            is_encrypted = False
            is_online = True

            # 1. Check direct configuration attributes
            config = attrs.get("configurations") or attrs.get("configuration")
            if isinstance(config, dict):
                e2e = config.get("e2e_encryption") or {}
                if e2e.get("enabled") is True:
                    is_encrypted = True

            # 2. Check included configuration
            rel_conf = dev.get("relationships", {}).get("configurations", {}).get("data", {})
            if isinstance(rel_conf, dict) and rel_conf.get("id") in included_confs:
                c_attrs = included_confs[rel_conf["id"]]
                if c_attrs.get("e2e_encryption", {}).get("enabled") is True:
                    is_encrypted = True

            # Check status
            status = attrs.get("status")
            if isinstance(status, dict):
                if status.get("online") is False:
                    is_online = False
            rel_status = dev.get("relationships", {}).get("status", {}).get("data", {})
            if isinstance(rel_status, dict) and rel_status.get("id") in included_statuses:
                s_attrs = included_statuses[rel_status["id"]]
                if s_attrs.get("online") is False:
                    is_online = False

            if is_encrypted:
                continue
            if not is_online:
                continue

            selected = dev
            break

        if not selected:
            if device_id:
                raise RingDeviceInaccessibleError(
                    f"Specified device {device_id} is encrypted, offline, or not found."
                )
            raise RingDeviceInaccessibleError(
                "No accessible unencrypted door camera found among account devices."
            )
        return selected

    async def start_whep(
        self,
        device_id: str,
        offer_sdp: str,
        token: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> tuple[str, str | None]:
        """Start a WHEP session.

        Returns (answer_sdp, session_id_or_url).
        """
        client = http or self._http
        headers = self._get_headers(token, content_type="application/sdp")
        url = f"{self.base_url}/v1/devices/{device_id}/media/streaming/whep/sessions"

        if client is not None:
            r = await client.post(url, content=offer_sdp, headers=headers)
            self._check_response_status(r, f"start_whep({device_id})")
            location = r.headers.get("Location")
            return r.text, location

        async with httpx.AsyncClient() as session:
            r = await session.post(url, content=offer_sdp, headers=headers)
            self._check_response_status(r, f"start_whep({device_id})")
            location = r.headers.get("Location")
            return r.text, location

    async def stop_whep(
        self,
        device_id: str,
        session_id_or_url: str,
        token: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        """Teardown a WHEP streaming session."""
        client = http or self._http
        headers = self._get_headers(token)

        # Handle either a full Location URL or just the session ID
        if session_id_or_url.startswith("http://") or session_id_or_url.startswith("https://"):
            url = session_id_or_url
        else:
            url = f"{self.base_url}/v1/devices/{device_id}/media/streaming/whep/sessions/{session_id_or_url}"

        try:
            if client is not None:
                r = await client.delete(url, headers=headers)
                if r.status_code != 404:
                    self._check_response_status(r, f"stop_whep({device_id})")
                return

            async with httpx.AsyncClient() as session:
                r = await session.delete(url, headers=headers)
                if r.status_code != 404:
                    self._check_response_status(r, f"stop_whep({device_id})")
        except httpx.HTTPError:
            # Session teardown failures during cleanup should not crash caller
            pass


# Standalone functions matching blueprint specification
async def list_devices(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    client = RingClient(token=token, http_client=http)
    return await client.list_devices()


async def start_whep(
    http: httpx.AsyncClient, token: str, device_id: str, offer_sdp: str
) -> tuple[str, str | None]:
    client = RingClient(token=token, http_client=http)
    return await client.start_whep(device_id, offer_sdp)


async def stop_whep(
    http: httpx.AsyncClient, token: str, device_id: str, session_id: str
) -> None:
    client = RingClient(token=token, http_client=http)
    await client.stop_whep(device_id, session_id)
