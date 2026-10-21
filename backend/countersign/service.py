"""Verification service shared by the HTTP API and the MCP server.

All rules about what may happen (synthetic evidence is refused, claims only
for DISPUTED verdicts after a re-check, actions need a recorded human
approval) live here so the two front doors cannot drift apart.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from countersign import trace as tracing
from countersign.bindings import StreamBinding
from countersign.evidence import EvidenceSink, PacketRef, S3Sink, draft_claim
from countersign.ledger import ACTIONS, Action, Approval, Ledger, Verification
from countersign.pipeline import VerificationResult, combine_results
from countersign.policy import Verdict
from countersign.trackers import EasyPostTrackers, TrackerLookup

log = logging.getLogger("countersign")

Verifier = Callable[[datetime, bool, StreamBinding | None], Awaitable[VerificationResult]]

RECHECK_DELAY_ENV = "RECHECK_DELAY_S"
DEFAULT_RECHECK_DELAY_S = 600.0  # 10 minutes; set RECHECK_DELAY_S=60 for demos


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
        trackers: TrackerLookup | None = None,
        recheck_delay_s: float | None = None,
        trace: tracing.TraceBus | None = None,
    ) -> None:
        self.verifier = verifier
        self.ledger = ledger or Ledger()
        self._sink = sink
        self.trackers: TrackerLookup = trackers or EasyPostTrackers()
        self.recheck_delay_s = (
            recheck_delay_s
            if recheck_delay_s is not None
            else float(os.environ.get(RECHECK_DELAY_ENV, DEFAULT_RECHECK_DELAY_S))
        )
        self.trace = trace or tracing.TraceBus()
        self.bindings: dict[str, StreamBinding] = {}  # keyed by tracker id or tracking code
        self._locks: dict[str, asyncio.Lock] = {}
        self._timers: set[asyncio.Future[None]] = set()

    # -- creation and capture ------------------------------------------------

    def start(
        self,
        *,
        source: str,
        delivered_at: datetime,
        tracking_code: str | None = None,
        tracker_id: str | None = None,
        event_id: str | None = None,
        simulate: bool = False,
    ) -> tuple[Verification, bool]:
        return self.ledger.create(
            source=source,
            delivered_at=delivered_at,
            tracking_code=tracking_code,
            tracker_id=tracker_id,
            event_id=event_id,
            simulate=simulate,
        )

    def binding_for(self, v: Verification) -> StreamBinding | None:
        return self.bindings.get(v.tracker_id or "") or self.bindings.get(v.tracking_code or "")

    async def run(self, vid: str) -> Verification:
        """First capture run. A DISPUTED result schedules a re-check."""
        v = self.get(vid)
        binding = self.binding_for(v)
        with tracing.bind(self.trace, vid):
            tracing.emit(
                "verification_started", "started", source=v.source, tracking_code=v.tracking_code,
                carrier_scan_at=v.delivered_at, simulate=v.simulate,
                stream=binding.stream if binding else None,
            )
            try:
                v.result = await self.verifier(v.delivered_at, v.simulate, binding)
                v.status = "complete"
                v.runs = 1
                v.checked_at = datetime.now(timezone.utc)
                self._schedule_recheck(v)  # before the terminal event, so it is last in the trace
                d = v.result.decision
                tracing.emit("verification_complete", "ok", verdict=d.verdict, rule=d.rule, reason=d.reason)
            except Exception as exc:
                log.exception("verification %s failed", vid)
                v.error = f"{type(exc).__name__}: {exc}"
                v.status = "failed"
                tracing.emit("verification_failed", "error", error=v.error)
        return v

    async def recheck(self, vid: str) -> Verification:
        """Capture again and re-run the policy over all frames so far.

        Safe to call at any time (the timer, or an agent via ``recheck_door``).
        A failed capture is recorded and leaves the verdict provisional.
        """
        async with self._locks.setdefault(vid, asyncio.Lock()):
            v = self.get(vid)
            if v.status != "complete" or v.result is None:
                raise ServiceError(409, f"verification is {v.status}, not complete")
            with tracing.bind(self.trace, vid):
                return await self._recheck_locked(v)

    async def _recheck_locked(self, v: Verification) -> Verification:
        assert v.result is not None
        tracing.emit("recheck_started", "started", run=v.runs + 1)
        try:
            new = await self.verifier(v.delivered_at, v.simulate, self.binding_for(v))
        except Exception as exc:
            log.exception("re-check of %s failed", v.id)
            v.recheck_error = f"{type(exc).__name__}: {exc}"
            tracing.emit("recheck_failed", "error", error=v.recheck_error)
            return v
        v.result = combine_results(v.result, new)
        v.runs += 1
        v.checked_at = datetime.now(timezone.utc)
        v.recheck_state = "done"
        v.recheck_due_at = None
        v.recheck_error = None
        d = v.result.decision
        tracing.emit("recheck_complete", "ok", verdict=d.verdict, rule=d.rule, reason=d.reason, runs=v.runs)
        # Approvals covered the earlier evidence; new frames need a fresh look.
        v.approvals.clear()
        v.claim_draft = v.evidence_location = v.evidence_sha256 = None
        return v

    def _schedule_recheck(self, v: Verification) -> None:
        assert v.result is not None
        if v.result.decision.verdict is not Verdict.DISPUTED:
            return
        if v.recheck_state != "none":
            return
        v.recheck_state = "scheduled"
        v.recheck_due_at = datetime.now(timezone.utc) + timedelta(seconds=self.recheck_delay_s)
        tracing.emit("recheck_scheduled", "info", due_at=v.recheck_due_at, delay_s=self.recheck_delay_s)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no loop (sync caller): the state stays "scheduled"
            return

        def fire() -> None:
            fut = asyncio.ensure_future(self._timed_recheck(v.id))
            self._timers.add(fut)
            fut.add_done_callback(self._timers.discard)

        loop.call_later(self.recheck_delay_s, fire)

    async def _timed_recheck(self, vid: str) -> None:
        try:
            await self.recheck(vid)
        except Exception:
            log.exception("scheduled re-check of %s failed", vid)

    # -- lookups ---------------------------------------------------------------

    def get(self, vid: str) -> Verification:
        v = self.ledger.get(vid)
        if v is None:
            raise ServiceError(404, "verification not found")
        return v

    def list(self, since: datetime | None = None) -> list[Verification]:
        return self.ledger.list(since)

    async def verify_tracking_code(
        self, tracking_code: str, carrier: str | None = None
    ) -> Verification | None:
        """Verification for a tracking code, reusing an existing one.

        Returns None when no carrier "delivered" scan is known yet (PENDING).
        """
        existing = self.ledger.find_by_tracking_code(tracking_code)
        if existing is not None and existing.status in ("complete", "pending"):
            return existing
        when = await self.trackers.delivered_at(tracking_code, carrier)
        if when is None:
            return None
        v, _ = self.start(source="mcp", delivered_at=when, tracking_code=tracking_code)
        await self.run(v.id)
        return v

    async def recheck_tracking_code(self, tracking_code: str) -> Verification:
        v = self.ledger.find_by_tracking_code(tracking_code)
        if v is None:
            raise ServiceError(404, f"no verification for tracking code {tracking_code}")
        if v.status == "failed":
            return await self.run(v.id)  # nothing to merge into yet
        return await self.recheck(v.id)

    # -- approval-gated actions -----------------------------------------------

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

    async def evidence_packet(self, vid: str) -> PacketRef:
        v = self.get(vid)
        _require_actionable(v, "evidence_packet")
        _require_approved(v, "evidence_packet")
        if v.evidence_location is None or v.evidence_sha256 is None:
            if self._sink is None:
                self._sink = S3Sink()
            ref = await self._sink.put_packet(v)
            v.evidence_location, v.evidence_sha256 = ref.location, ref.sha256
        return PacketRef(v.evidence_location, v.evidence_sha256)

    async def claim_packet(self, vid: str) -> dict[str, Any]:
        """Packet + claim draft together. Checks BOTH gates before doing either,
        so a missing approval never leaves a half-built result."""
        v = self.get(vid)
        for action in ACTIONS:
            _require_actionable(v, action)
        for action in ACTIONS:
            _require_approved(v, action)
        draft = self.claim_draft(vid)
        ref = await self.evidence_packet(vid)
        return {
            "verification_id": vid,
            "packet_url": ref.location,
            "sha256": ref.sha256,
            "draft_text": draft["draft_text"],
            "requires_approval": True,  # a human still reviews and sends the claim
        }


def _require_actionable(v: Verification, action: Action) -> None:
    """Refuse approvals/actions that must never happen, before asking a human."""
    if action not in ACTIONS:
        raise ServiceError(422, "unknown action")
    if v.status != "complete" or v.result is None:
        raise ServiceError(409, f"verification is {v.status}, not complete")
    if v.synthetic:
        raise ServiceError(409, "synthetic/simulated evidence can never back a claim or packet")
    verdict = v.result.decision.verdict
    if verdict is Verdict.DISPUTED and v.recheck_state != "done":
        due = v.recheck_due_at.isoformat() if v.recheck_due_at else "soon"
        raise ServiceError(
            409,
            f"DISPUTED is provisional until the re-check runs (due {due}); "
            "claims and packets wait for it",
        )
    if action == "claim_draft" and verdict is not Verdict.DISPUTED:
        raise ServiceError(409, "claims can only be drafted for DISPUTED verdicts")


def _require_approved(v: Verification, action: Action) -> None:
    ap = v.approvals.get(action)
    if ap is None or not ap.approved:
        raise ServiceError(
            409, {"error": "approval_required", "action": action, "requires_approval": True}
        )
