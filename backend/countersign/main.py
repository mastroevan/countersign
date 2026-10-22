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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import AwareDatetime, BaseModel, Field

from countersign.aws import PixelBedrock, make_client
from countersign.evidence import EvidenceSink
from countersign.bindings import SCENARIOS_ENV, StreamBinding
from countersign.frames import OFFLINE_ENV, forced_timeout_frames
from countersign.ledger import Ledger
from countersign.mcp_server import build_mcp
from countersign.pipeline import VerificationResult, verify_delivery
from countersign.policy import PolicyConfig
from countersign.ring_client import RingClient
from countersign.trackers import TrackerLookup, delivered_at_from_result
from countersign.trace import TraceBus, sse_stream
from countersign.service import ServiceError, VerificationService, Verifier
from countersign.vision_judge import device_tz_from_env

log = logging.getLogger("countersign")

WEBHOOK_SECRET_ENV = "EASYPOST_WEBHOOK_SECRET"


class VerifyRequest(BaseModel):
    delivered_at: AwareDatetime
    tracking_code: str | None = None
    simulate: bool = False


class BindingRequest(BaseModel):
    key: str = Field(min_length=1, description="tracker id (trk_...) or tracking code")
    stream: Literal["package", "motion", "timeout"]
    device_id: str | None = None
    offline: bool = False


class ApprovalRequest(BaseModel):
    action: Literal["claim_draft", "evidence_packet"]
    approved: bool
    approver: str = Field(min_length=1, max_length=200)


def default_verifier() -> Verifier:
    """Real pipeline. Clients are built lazily so the app boots without AWS/Ring."""
    ring = RingClient()
    bedrock: Any = None

    async def run(
        delivered_at: datetime, simulate: bool, binding: StreamBinding | None = None
    ) -> VerificationResult:
        nonlocal bedrock
        if bedrock is None:
            if os.environ.get("COUNTERSIGN_STUB_BEDROCK") == "true" or os.environ.get("BEDROCK_MODEL_ID") in ("x", "stub", "stub-model", "pixel"):
                bedrock = PixelBedrock()
            else:
                bedrock = make_client("bedrock-runtime")
        offline = simulate or os.environ.get(OFFLINE_ENV) == "true" or bool(binding and binding.offline)
        extra: dict[str, Any] = {}
        if binding:
            if binding.device_id:
                extra["device_id"] = binding.device_id
            if binding.stream == "timeout":
                extra["frames_fn"] = forced_timeout_frames
            if binding.offline:
                extra["synthetic_has_parcel"] = binding.stream == "package"
        return await verify_delivery(
            delivered_at,
            ring,
            bedrock,
            device_tz=device_tz_from_env(),
            force_synthetic=offline,
            # Simulated runs must be able to reach a verdict; the service layer
            # still refuses claims and packets for synthetic evidence.
            config=PolicyConfig(allow_synthetic=offline),
            **extra,
        )

    return run


def create_app(
    verifier: Verifier | None = None,
    ledger: Ledger | None = None,
    sink: EvidenceSink | None = None,
    trackers: TrackerLookup | None = None,
    recheck_delay_s: float | None = None,
    trace: TraceBus | None = None,
) -> FastAPI:
    service = VerificationService(
        verifier or default_verifier(), ledger, sink, trackers, recheck_delay_s, trace
    )
    mcp_app = build_mcp(service).http_app(path="/")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_app.lifespan(mcp_app):
            yield

    app = FastAPI(title="Countersign", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
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
        delivered_at = delivered_at_from_result(result)
        if delivered_at is None:
            raise HTTPException(422, "no timezone-aware delivery timestamp in event")

        v, created = service.start(
            source="webhook",
            delivered_at=delivered_at,
            tracking_code=result.get("tracking_code"),
            tracker_id=result.get("id"),
            event_id=event.get("id"),
        )
        if created:
            _trace_webhook(service.trace, v.id, event, bool(secret))
            tasks.add_task(service.run, v.id)
        return {"id": v.id, "status": v.status, "duplicate": not created}

    @app.get("/api/trace")
    async def trace_stream(
        request: Request,
        verification_id: str | None = None,
        last_event_id: int | None = None,
        follow: bool = True,
    ) -> StreamingResponse:
        """Server-Sent Events: pipeline stages as they happen.

        Replays history after ``Last-Event-ID`` (header or ``last_event_id``),
        then follows live unless ``follow=false``.
        """
        header = request.headers.get("last-event-id", "")
        last = last_event_id if last_event_id is not None else (int(header) if header.isdigit() else 0)
        return StreamingResponse(
            sse_stream(service.trace, request.is_disconnected, verification_id, last, follow),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/bindings", status_code=201)
    async def set_binding(req: BindingRequest) -> dict[str, Any]:
        """Bind a tracker to a demo stream. Off unless COUNTERSIGN_SCENARIOS=true."""
        if os.environ.get(SCENARIOS_ENV) != "true":
            raise HTTPException(404, "scenario bindings are disabled")
        service.bindings[req.key] = StreamBinding(req.stream, req.device_id, req.offline)
        return {"key": req.key, "stream": req.stream, "device_id": req.device_id, "offline": req.offline}

    @app.get("/api/ledger")
    async def ledger_alias() -> list[dict[str, Any]]:
        return [v.to_dict() for v in service.list()]

    @app.get("/verifications")
    async def list_verifications() -> list[dict[str, Any]]:
        return [v.to_dict() for v in service.list()]

    @app.get("/verifications/{vid}/frames/{frame_id}.jpg")
    async def get_frame(vid: str, frame_id: str) -> Response:
        v = service.get(vid)
        for f in v.result.frames if v.result else []:
            if f.frame_id == frame_id:
                return Response(f.jpeg, media_type="image/jpeg")
        raise HTTPException(404, "frame not found")

    @app.get("/verifications/{vid}")
    async def get_verification(vid: str) -> dict[str, Any]:
        return service.get(vid).to_dict()

    @app.post("/verifications/{vid}/approvals")
    async def record_approval(vid: str, req: ApprovalRequest) -> dict[str, Any]:
        return service.record_approval(vid, req.action, req.approved, req.approver).to_dict()

    @app.post("/verifications/{vid}/recheck")
    async def recheck(vid: str) -> dict[str, Any]:
        """Re-check now (what the timer does after RECHECK_DELAY_S)."""
        return (await service.recheck(vid)).to_dict()

    @app.post("/verifications/{vid}/claim-draft")
    async def make_claim_draft(vid: str) -> dict[str, Any]:
        return service.claim_draft(vid)

    @app.post("/verifications/{vid}/evidence-packet")
    async def make_evidence_packet(vid: str) -> dict[str, Any]:
        ref = await service.evidence_packet(vid)
        return {"location": ref.location, "sha256": ref.sha256}

    return app


def _trace_webhook(bus: TraceBus, vid: str, event: dict[str, Any], signature_checked: bool) -> None:
    """Show the raw webhook in the trace, but only for EasyPost test-mode events."""
    mode = event.get("mode")
    result = event.get("result") or {}
    data: dict[str, Any] = {
        "mode": mode,
        "event_id": event.get("id"),
        "description": event.get("description"),
        "tracking_code": result.get("tracking_code"),
        "carrier_status": result.get("status"),
        "signature_checked": signature_checked,
    }
    if mode == "test":
        data["payload"] = event
    bus.publish(vid, "webhook_received", "ok", **data)


def _valid_signature(secret: str, body: bytes, headers: Any) -> bool:
    """EasyPost: ``X-Hmac-Signature: hmac-sha256-hex=<hex of HMAC(secret, body)>``."""
    given = headers.get("x-hmac-signature", "")
    key = unicodedata.normalize("NFKD", secret).encode()
    expected = "hmac-sha256-hex=" + hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(given, expected)


app = create_app()
