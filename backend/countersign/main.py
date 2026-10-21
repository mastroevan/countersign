"""FastAPI app: EasyPost webhook, manual verification, approval-gated actions.

Run: ``uvicorn countersign.main:app --reload --port 8000``

Flow: a carrier "delivered" event creates a pending Verification, the pipeline
runs in the background, and the policy (never the model) sets the verdict.
Claim drafts and evidence packets only run after an explicit human approval
recorded via ``POST /verifications/{id}/approvals``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import unicodedata
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field

from countersign.aws import make_client
from countersign.evidence import EvidenceSink
from countersign.frames import OFFLINE_ENV
from countersign.ledger import Ledger
from countersign.mcp_server import build_mcp
from countersign.pipeline import VerificationResult, verify_delivery
from countersign.policy import PolicyConfig
from countersign.ring_client import RingClient
from countersign.service import ServiceError, VerificationService
from countersign.vision_judge import device_tz_from_env

log = logging.getLogger("countersign")

WEBHOOK_SECRET_ENV = "EASYPOST_WEBHOOK_SECRET"
Verifier = Callable[[datetime, bool], Awaitable[VerificationResult]]


class VerifyRequest(BaseModel):
    delivered_at: AwareDatetime
    tracking_code: str | None = None
    simulate: bool = False


class ApprovalRequest(BaseModel):
    action: Literal["claim_draft", "evidence_packet"]
    approved: bool
    approver: str = Field(min_length=1, max_length=200)


def default_verifier() -> Verifier:
    """Real pipeline. Clients are built lazily so the app boots without AWS/Ring."""
    ring = RingClient()
    bedrock: Any = None

    async def run(delivered_at: datetime, simulate: bool) -> VerificationResult:
        nonlocal bedrock
        if bedrock is None:
            bedrock = make_client("bedrock-runtime")
        offline = simulate or os.environ.get(OFFLINE_ENV) == "true"
        return await verify_delivery(
            delivered_at,
            ring,
            bedrock,
            device_tz=device_tz_from_env(),
            force_synthetic=offline,
            # Simulated runs must be able to reach a verdict; the service layer
            # still refuses claims and packets for synthetic evidence.
            config=PolicyConfig(allow_synthetic=offline),
        )

    return run


def create_app(
    verifier: Verifier | None = None,
    ledger: Ledger | None = None,
    sink: EvidenceSink | None = None,
) -> FastAPI:
    service = VerificationService(verifier or default_verifier(), ledger, sink)
    mcp_app = build_mcp(service).http_app(path="/")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_app.lifespan(mcp_app):
            yield

    app = FastAPI(title="Countersign", lifespan=lifespan)
    app.mount("/mcp", mcp_app)  # Streamable HTTP MCP endpoint at /mcp/

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/verify", status_code=202)
    async def verify(req: VerifyRequest, tasks: BackgroundTasks) -> dict[str, Any]:
        v, _ = service.start(
            source="manual",
            delivered_at=req.delivered_at,
            tracking_code=req.tracking_code,
            simulate=req.simulate,
        )
        tasks.add_task(service.run, v.id)
        return {"id": v.id, "status": v.status, "requires_approval": True}

    @app.post("/webhooks/easypost", status_code=202)
    async def easypost_webhook(request: Request, tasks: BackgroundTasks) -> dict[str, Any]:
        raw = await request.body()
        secret = os.environ.get(WEBHOOK_SECRET_ENV)
        if secret and not _valid_signature(secret, raw, request.headers):
            raise HTTPException(401, "invalid webhook signature")
        try:
            event = json.loads(raw)
            result = event["result"]
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "malformed EasyPost event")

        if result.get("status") != "delivered":
            return {"ignored": f"status is {result.get('status')!r}, not delivered"}
        delivered_at = _delivered_at(result)
        if delivered_at is None:
            raise HTTPException(422, "no timezone-aware delivery timestamp in event")

        v, created = service.start(
            source="webhook",
            delivered_at=delivered_at,
            tracking_code=result.get("tracking_code"),
            event_id=event.get("id"),
        )
        if created:
            tasks.add_task(service.run, v.id)
        return {"id": v.id, "status": v.status, "duplicate": not created}

    @app.get("/verifications")
    async def list_verifications() -> list[dict[str, Any]]:
        return [v.to_dict() for v in service.list()]

    @app.get("/verifications/{vid}")
    async def get_verification(vid: str) -> dict[str, Any]:
        return service.get(vid).to_dict()

    @app.post("/verifications/{vid}/approvals")
    async def record_approval(vid: str, req: ApprovalRequest) -> dict[str, Any]:
        return service.record_approval(vid, req.action, req.approved, req.approver).to_dict()

    @app.post("/verifications/{vid}/claim-draft")
    async def make_claim_draft(vid: str) -> dict[str, Any]:
        return service.claim_draft(vid)

    @app.post("/verifications/{vid}/evidence-packet")
    async def make_evidence_packet(vid: str) -> dict[str, Any]:
        return {"location": await service.evidence_packet(vid)}

    return app


def _valid_signature(secret: str, body: bytes, headers: Any) -> bool:
    """EasyPost: ``X-Hmac-Signature: hmac-sha256-hex=<hex of HMAC(secret, body)>``."""
    given = headers.get("x-hmac-signature", "")
    key = unicodedata.normalize("NFKD", secret).encode()
    expected = "hmac-sha256-hex=" + hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(given, expected)


def _delivered_at(result: dict[str, Any]) -> datetime | None:
    details = [
        d for d in result.get("tracking_details") or [] if d.get("status") == "delivered"
    ]
    if not details:
        return None
    raw = details[-1].get("datetime")
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


app = create_app()
