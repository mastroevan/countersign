"""In-memory verification ledger with approval state.

Stand-in for the DynamoDB ledger. The interface is deliberately small so a
DynamoDB-backed class can replace ``Ledger`` without touching the API layer.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from countersign.pipeline import VerificationResult

Action = Literal["claim_draft", "evidence_packet"]
ACTIONS: tuple[Action, ...] = ("claim_draft", "evidence_packet")
Status = Literal["pending", "complete", "failed"]
RecheckState = Literal["none", "scheduled", "done"]


@dataclass
class Approval:
    action: Action
    approved: bool
    approver: str
    at: datetime


@dataclass
class Verification:
    id: str
    source: str  # "webhook" | "manual"
    status: Status
    created_at: datetime
    delivered_at: datetime
    tracking_code: str | None = None
    event_id: str | None = None
    simulate: bool = False
    result: VerificationResult | None = None
    error: str | None = None
    approvals: dict[Action, Approval] = field(default_factory=dict)
    claim_draft: dict[str, Any] | None = None
    evidence_location: str | None = None
    evidence_sha256: str | None = None
    checked_at: datetime | None = None  # when the latest capture run finished
    # A DISPUTED verdict is provisional until a re-check has run.
    recheck_state: RecheckState = "none"
    recheck_due_at: datetime | None = None
    recheck_error: str | None = None
    runs: int = 0  # capture runs merged into ``result``

    @property
    def synthetic(self) -> bool:
        """True if any captured frame was synthetic, even if the policy dropped it."""
        if self.simulate:
            return True
        return bool(self.result and any(f.source == "synthetic" for f in self.result.frames))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "delivered_at": self.delivered_at.isoformat(),
            "tracking_code": self.tracking_code,
            "event_id": self.event_id,
            "simulate": self.simulate,
            "synthetic": self.synthetic,
            "error": self.error,
            "result": self.result.to_dict() if self.result else None,
            "requires_approval": True,
            "approvals": {
                a: {
                    "approved": ap.approved,
                    "approver": ap.approver,
                    "at": ap.at.isoformat(),
                }
                for a, ap in self.approvals.items()
            },
            "claim_draft": self.claim_draft,
            "evidence_location": self.evidence_location,
            "evidence_sha256": self.evidence_sha256,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "recheck_state": self.recheck_state,
            "recheck_due_at": self.recheck_due_at.isoformat() if self.recheck_due_at else None,
            "recheck_error": self.recheck_error,
            "runs": self.runs,
        }


class Ledger:
    def __init__(self) -> None:
        self._items: dict[str, Verification] = {}
        self._events: dict[str, str] = {}  # webhook event id -> verification id
        self._lock = threading.Lock()

    def create(
        self,
        *,
        source: str,
        delivered_at: datetime,
        tracking_code: str | None = None,
        event_id: str | None = None,
        simulate: bool = False,
    ) -> tuple[Verification, bool]:
        """Create a pending record. Returns (record, created); a repeated
        webhook ``event_id`` returns the existing record with created=False."""
        with self._lock:
            if event_id and event_id in self._events:
                return self._items[self._events[event_id]], False
            v = Verification(
                id=uuid.uuid4().hex,
                source=source,
                status="pending",
                created_at=datetime.now(timezone.utc),
                delivered_at=delivered_at,
                tracking_code=tracking_code,
                event_id=event_id,
                simulate=simulate,
            )
            self._items[v.id] = v
            if event_id:
                self._events[event_id] = v.id
            return v, True

    def get(self, verification_id: str) -> Verification | None:
        return self._items.get(verification_id)

    def list(self, since: datetime | None = None) -> list[Verification]:
        items = [v for v in self._items.values() if since is None or v.created_at >= since]
        return sorted(items, key=lambda v: v.created_at, reverse=True)

    def find_by_tracking_code(self, tracking_code: str) -> Verification | None:
        """Most recent verification for a tracking code."""
        for v in self.list():
            if v.tracking_code == tracking_code:
                return v
        return None
