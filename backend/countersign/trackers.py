"""Carrier scan lookup by tracking code.

Used when an agent asks about a tracking code that has no webhook-created
ledger entry yet. The EasyPost REST call shape (POST /v2/trackers, HTTP basic
auth with the API key, ``tracking_details`` with a ``delivered`` entry) follows
EasyPost's tracking guide but has not been exercised against the live API.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Protocol

import httpx

EASYPOST_KEY_ENV = "EASYPOST_API_KEY"
EASYPOST_URL = "https://api.easypost.com/v2/trackers"


class TrackerLookup(Protocol):
    async def delivered_at(self, tracking_code: str, carrier: str | None) -> datetime | None:
        """Carrier "delivered" scan time, or None if not (yet) delivered/known."""


def delivered_at_from_result(result: dict[str, Any]) -> datetime | None:
    """Timezone-aware time of the last ``delivered`` tracking detail, else None."""
    details = [d for d in result.get("tracking_details") or [] if d.get("status") == "delivered"]
    if not details:
        return None
    raw = details[-1].get("datetime")
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


class EasyPostTrackers:
    def __init__(self, api_key: str | None = None, http: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key or os.environ.get(EASYPOST_KEY_ENV, "")
        self._http = http

    async def delivered_at(self, tracking_code: str, carrier: str | None) -> datetime | None:
        if not self.api_key:
            return None  # no key configured: only webhook-fed entries are known
        body: dict[str, Any] = {"tracker": {"tracking_code": tracking_code}}
        if carrier:
            body["tracker"]["carrier"] = carrier
        auth = (self.api_key, "")
        if self._http is not None:
            r = await self._http.post(EASYPOST_URL, json=body, auth=auth)
        else:
            async with httpx.AsyncClient(timeout=15) as http:
                r = await http.post(EASYPOST_URL, json=body, auth=auth)
        if r.status_code >= 400:
            raise RuntimeError(f"EasyPost tracker lookup failed (HTTP {r.status_code})")
        result = r.json()
        if result.get("status") != "delivered":
            return None
        return delivered_at_from_result(result)
