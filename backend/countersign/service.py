"""Verification service shared by the HTTP API and the MCP server.

All rules about what may happen (synthetic evidence is refused, claims only
for DISPUTED verdicts, actions need a recorded human approval) live here so
the two front doors cannot drift apart.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from countersign.evidence import EvidenceSink, S3Sink, draft_claim
from countersign.ledger import ACTIONS, Action, Approval, Ledger, Verification
from countersign.pipeline import VerificationResult
from countersign.policy import Verdict

log = logging.getLogger("countersign")

Verifier = Callable[[datetime, bool], Awaitable[VerificationResult]]


class ServiceError(Exception):
    """A refused operation. ``status`` follows HTTP semantics (404/409/422)."""

    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status = status
        self.detail = detail


class VerificationService:
    def __init__(
        self,
        verifier: Verifier,
        ledger: Ledger | None = None,
        sink: EvidenceSink | None = None,
    ) -> None:
        self.verifier = verifier
        self.ledger = ledger or Ledger()
        self._sink = sink

    def start(
        self,
        *,
        source: str,
        delivered_at: datetime,
        tracking_code: str | None = None,
        event_id: str | None = None,
        simulate: bool = False,
    ) -> tuple[Verification, bool]:
        return self.ledger.create(
            source=source,
            delivered_at=delivered_at,
            tracking_code=tracking_code,
            event_id=event_id,
            simulate=simulate,
        )

    async def run(self, vid: str) -> Verification:
        v = self.get(vid)
        try:
            v.result = await self.verifier(v.delivered_at, v.simulate)
            v.status = "complete"
        except Exception as exc:
            log.exception("verification %s failed", vid)
            v.error = f"{type(exc).__name__}: {exc}"
            v.status = "failed"
        return v

    def get(self, vid: str) -> Verification:
        v = self.ledger.get(vid)
        if v is None:
            raise ServiceError(404, "verification not found")
        return v

    def list(self) -> list[Verification]:
        return self.ledger.list()

    def record_approval(
        self, vid: str, action: Action, approved: bool, approver: str
    ) -> Verification:
        v = self.get(vid)
        _require_actionable(v, action)
        if not approver.strip():
            raise ServiceError(422, "approver must name a person")
        v.approvals[action] = Approval(
            action, approved, approver.strip(), datetime.now(timezone.utc)
        )
        return v

    def claim_draft(self, vid: str) -> dict[str, Any]:
        v = self.get(vid)
        _require_actionable(v, "claim_draft")
        _require_approved(v, "claim_draft")
        if v.claim_draft is None:
            v.claim_draft = draft_claim(v)
        return v.claim_draft

    async def evidence_packet(self, vid: str) -> str:
        v = self.get(vid)
        _require_actionable(v, "evidence_packet")
        _require_approved(v, "evidence_packet")
        if v.evidence_location is None:
            if self._sink is None:
                self._sink = S3Sink()
            v.evidence_location = await self._sink.put_packet(v)
        return v.evidence_location


def _require_actionable(v: Verification, action: Action) -> None:
    """Refuse approvals/actions that must never happen, before asking a human."""
    if action not in ACTIONS:
        raise ServiceError(422, "unknown action")
    if v.status != "complete" or v.result is None:
        raise ServiceError(409, f"verification is {v.status}, not complete")
    if v.synthetic:
        raise ServiceError(409, "synthetic/simulated evidence can never back a claim or packet")
    if action == "claim_draft" and v.result.decision.verdict is not Verdict.DISPUTED:
        raise ServiceError(409, "claims can only be drafted for DISPUTED verdicts")


def _require_approved(v: Verification, action: Action) -> None:
    ap = v.approvals.get(action)
    if ap is None or not ap.approved:
        raise ServiceError(
            409, {"error": "approval_required", "action": action, "requires_approval": True}
        )
