"""MCP server (FastMCP, Streamable HTTP) mounted by the FastAPI app at /mcp/.

Deliberately has NO approval tool: an agent connected here can request a
verification and ask for a claim draft or evidence packet, but those only
succeed after a named human records approval through the dashboard/HTTP API.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from countersign.service import ServiceError, VerificationService

INSTRUCTIONS = (
    "Countersign checks a carrier 'delivered' scan against doorbell-camera "
    "evidence. Verdicts (VERIFIED / DISPUTED / INCONCLUSIVE) come from a "
    "deterministic policy, never from a model. Drafting a claim and storing an "
    "evidence packet require explicit human approval (requires_approval: true); "
    "you cannot grant it. Only describe the step/porch and parcels."
)


def build_mcp(service: VerificationService) -> FastMCP:
    mcp = FastMCP("countersign", instructions=INSTRUCTIONS)

    def guard(exc: ServiceError) -> ToolError:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        if isinstance(exc.detail, dict) and exc.detail.get("error") == "approval_required":
            detail += " — a human must approve this action in the Countersign dashboard first."
        return ToolError(detail)

    @mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": False})
    async def verify_delivery(
        delivered_at: str, tracking_code: str | None = None, simulate: bool = False
    ) -> dict[str, Any]:
        """Verify a carrier delivery. ``delivered_at`` is an ISO 8601 timestamp WITH
        timezone (e.g. 2026-10-15T12:00:00Z). Captures camera frames, runs the vision
        judge, and returns the policy verdict. ``simulate`` uses synthetic frames,
        whose results can never be used for claims or evidence packets."""
        try:
            when = datetime.fromisoformat(delivered_at.replace("Z", "+00:00"))
        except ValueError:
            raise ToolError("delivered_at must be an ISO 8601 timestamp")
        if when.tzinfo is None:
            raise ToolError("delivered_at must include a timezone offset")
        v, _ = service.start(
            source="mcp", delivered_at=when, tracking_code=tracking_code, simulate=simulate
        )
        await service.run(v.id)
        return v.to_dict()

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_verification(verification_id: str) -> dict[str, Any]:
        """Fetch one verification, including per-frame evidence and approval state."""
        try:
            return service.get(verification_id).to_dict()
        except ServiceError as exc:
            raise guard(exc)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_verifications() -> list[dict[str, Any]]:
        """List verifications, newest first."""
        return [v.to_dict() for v in service.list()]

    @mcp.tool(annotations={"readOnlyHint": False})
    async def draft_claim(verification_id: str) -> dict[str, Any]:
        """Draft a not-delivered claim. Only for DISPUTED verdicts on live evidence,
        and only after a human has approved 'claim_draft' for this verification."""
        try:
            return service.claim_draft(verification_id)
        except ServiceError as exc:
            raise guard(exc)

    @mcp.tool(annotations={"readOnlyHint": False})
    async def store_evidence_packet(verification_id: str) -> dict[str, str]:
        """Store the evidence packet (manifest + unmodified frames) in S3. Requires
        prior human approval of 'evidence_packet' for this verification."""
        try:
            return {"location": await service.evidence_packet(verification_id)}
        except ServiceError as exc:
            raise guard(exc)

    return mcp
