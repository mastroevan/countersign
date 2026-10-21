"""MCP server (FastMCP, Streamable HTTP) mounted by the FastAPI app at /mcp/.

Tools follow the strategy blueprint, keyed by tracking code so a voice client
that only knows "my package" can use them: ``verify_delivery``,
``recheck_door``, ``get_delivery_ledger``, ``build_claim_packet``.

Deliberately has NO approval tool: ``build_claim_packet`` only succeeds after a
named human records approval through the dashboard/HTTP API.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from countersign.ledger import Verification
from countersign.reports import report
from countersign.service import ServiceError, VerificationService

PUBLIC_BASE_URL_ENV = "PUBLIC_BASE_URL"

INSTRUCTIONS = (
    "Countersign checks a carrier 'delivered' scan against doorbell-camera "
    "evidence. Verdicts (VERIFIED / DISPUTED / INCONCLUSIVE) come from a "
    "deterministic policy, never from a model. A DISPUTED verdict is provisional "
    "until a re-check has run. Building a claim packet requires explicit human "
    "approval (requires_approval: true); you cannot grant it. Only describe the "
    "step/porch and parcels, never people or vehicles."
)


def build_mcp(service: VerificationService, public_base_url: str | None = None) -> FastMCP:
    mcp = FastMCP("countersign", instructions=INSTRUCTIONS)
    base = public_base_url or os.environ.get(PUBLIC_BASE_URL_ENV, "http://localhost:8000")

    def err(exc: ServiceError) -> ToolError:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        if isinstance(exc.detail, dict) and exc.detail.get("error") == "approval_required":
            detail += " — a human must approve this in the Countersign dashboard first."
        return ToolError(detail)

    def view(v: Verification) -> dict[str, Any]:
        if v.status == "failed":
            # e.g. expired Ring token: surfaced as an error, never as a verdict
            raise ToolError(f"The check failed and produced no verdict: {v.error}")
        return report(v, base)

    def pending(tracking_code: str) -> dict[str, Any]:
        return {
            "tracking_code": tracking_code,
            "status": "PENDING",
            "carrier_scan_at": None,
            "checked_at": None,
            "confidence": None,
            "evidence": [],
            "reason": "No carrier delivery scan found for this tracking code yet.",
            "requires_approval": True,
        }

    @mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True})
    async def verify_delivery(tracking_code: str, carrier: str | None = None) -> dict[str, Any]:
        """Has this package actually arrived? Checks the carrier's delivered claim
        against the Ring camera and returns status (VERIFIED, DISPUTED, INCONCLUSIVE
        or PENDING), carrier_scan_at, checked_at, confidence, evidence frames with
        watermark times, and a plain-language reason. Reuses an earlier check for
        the same tracking code; call recheck_door for fresh frames."""
        try:
            v = await service.verify_tracking_code(tracking_code, carrier)
        except ServiceError as exc:
            raise err(exc)
        except RuntimeError as exc:  # carrier lookup failure
            raise ToolError(f"Could not look up the carrier scan: {exc}")
        return pending(tracking_code) if v is None else view(v)

    @mcp.tool(annotations={"readOnlyHint": False})
    async def recheck_door(tracking_code: str) -> dict[str, Any]:
        """Look at the door again now and re-evaluate. Same shape as verify_delivery.
        New frames are added to the earlier ones and the policy re-runs on all of them."""
        try:
            return view(await service.recheck_tracking_code(tracking_code))
        except ServiceError as exc:
            raise err(exc)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_delivery_ledger(since: str | None = None) -> list[dict[str, Any]]:
        """List ledger entries, newest first. ``since`` is an optional ISO 8601 date
        or timestamp (dates mean midnight UTC)."""
        when = _parse_since(since)
        return [report(v, base, include_evidence=False) for v in service.list(when)]

    @mcp.tool(annotations={"readOnlyHint": False})
    async def build_claim_packet(tracking_code: str) -> dict[str, Any]:
        """Build the evidence packet (packet_url, sha256) and claim draft_text for a
        DISPUTED delivery. Needs a finished re-check and a human's approval of both
        'claim_draft' and 'evidence_packet'. The claim is never sent automatically."""
        v = service.ledger.find_by_tracking_code(tracking_code)
        if v is None:
            raise ToolError(f"No verification for tracking code {tracking_code}.")
        try:
            return await service.claim_packet(v.id)
        except ServiceError as exc:
            raise err(exc)

    return mcp


def _parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    try:
        if len(since) == 10:
            d = date.fromisoformat(since)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        raise ToolError("since must be an ISO 8601 date or timestamp")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
