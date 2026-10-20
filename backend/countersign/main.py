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
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field

from countersign.evidence import EvidenceSink, S3Sink, draft_claim
from countersign.frames import OFFLINE_ENV
from countersign.ledger import ACTIONS, Action, Approval, Ledger, Verification
from countersign.pipeline import VerificationResult, verify_delivery
from countersign.policy import PolicyConfig, Verdict
from countersign.ring_client import RingClient
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
            import boto3

            bedrock = boto3.client("bedrock-runtime")
        offline = simulate or os.environ.get(OFFLINE_ENV) == "true"
        return await verify_delivery(
            delivered_at,
            ring,
            bedrock,
            device_tz=device_tz_from_env(),
            force_synthetic=offline,
            config=PolicyConfig(),
        )

    return run


def create_app(
    verifier: Verifier | None = None,
    ledger: Ledger | None = None,
    sink: EvidenceSink | None = None,
) -> FastAPI:
    app = FastAPI(title="Countersign")
    store = ledger or Ledger()
    run_verifier = verifier or default_verifier()
    sinks: list[EvidenceSink] = [sink] if sink else []

    def get_sink() -> EvidenceSink:
        if not sinks:
            sinks.append(S3Sink())
        return sinks[0]

    async def run_verification(vid: str) -> None:
        v = store.get(vid)
        assert v is not None
        try:
            v.result = await run_verifier(v.delivered_at, v.simulate)
            v.status = "complete"
        except Exception as exc:
            log.exception("verification %s failed", vid)
            v.error = f"{type(exc).__name__}: {exc}"
            v.status = "failed"

    def need(vid: str) -> Verification:
        v = store.get(vid)
        if v is None:
            raise HTTPException(404, "verification not found")
        return v

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/verify", status_code=202)
    async def verify(req: VerifyRequest, tasks: BackgroundTasks) -> dict[str, Any]:
        v, _ = store.create(
            source="manual",
            delivered_at=req.delivered_at,
            tracking_code=req.tracking_code,
            simulate=req.simulate,
        )
        tasks.add_task(run_verification, v.id)
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

        v, created = store.create(
            source="webhook",
            delivered_at=delivered_at,
            tracking_code=result.get("tracking_code"),
            event_id=event.get("id"),
        )
        if created:
            tasks.add_task(run_verification, v.id)
        return {"id": v.id, "status": v.status, "duplicate": not created}

    @app.get("/verifications")
    async def list_verifications() -> list[dict[str, Any]]:
        return [v.to_dict() for v in store.list()]

    @app.get("/verifications/{vid}")
    async def get_verification(vid: str) -> dict[str, Any]:
        return need(vid).to_dict()

    @app.post("/verifications/{vid}/approvals")
    async def record_approval(vid: str, req: ApprovalRequest) -> dict[str, Any]:
        v = need(vid)
        _require_actionable(v, req.action)
        if not req.approver.strip():
            raise HTTPException(422, "approver must name a person")
        v.approvals[req.action] = Approval(
            req.action, req.approved, req.approver.strip(), datetime.now(timezone.utc)
        )
        return v.to_dict()

    @app.post("/verifications/{vid}/claim-draft")
    async def make_claim_draft(vid: str) -> dict[str, Any]:
        v = need(vid)
        _require_actionable(v, "claim_draft")
        _require_approved(v, "claim_draft")
        if v.claim_draft is None:
            v.claim_draft = draft_claim(v)
        return v.claim_draft

    @app.post("/verifications/{vid}/evidence-packet")
    async def make_evidence_packet(vid: str) -> dict[str, Any]:
        v = need(vid)
        _require_actionable(v, "evidence_packet")
        _require_approved(v, "evidence_packet")
        if v.evidence_location is None:
            v.evidence_location = await get_sink().put_packet(v)
        return {"location": v.evidence_location}

    return app


def _require_actionable(v: Verification, action: Action) -> None:
    """Refuse approvals/actions that must never happen, before asking a human."""
    if action not in ACTIONS:
        raise HTTPException(422, "unknown action")
    if v.status != "complete" or v.result is None:
        raise HTTPException(409, f"verification is {v.status}, not complete")
    if v.synthetic:
        raise HTTPException(409, "synthetic/simulated evidence can never back a claim or packet")
    if action == "claim_draft" and v.result.decision.verdict is not Verdict.DISPUTED:
        raise HTTPException(409, "claims can only be drafted for DISPUTED verdicts")


def _require_approved(v: Verification, action: Action) -> None:
    ap = v.approvals.get(action)
    if ap is None or not ap.approved:
        raise HTTPException(
            409, {"error": "approval_required", "action": action, "requires_approval": True}
        )


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
