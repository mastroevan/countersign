"""Consumer-facing views of a Verification (the MCP tool output shapes)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from countersign.ledger import Verification


def frame_url(base_url: str, v: Verification, frame_id: str) -> str:
    return f"{base_url.rstrip('/')}/verifications/{v.id}/frames/{frame_id}.jpg"


def report(v: Verification, base_url: str, include_evidence: bool = True) -> dict[str, Any]:
    """status / carrier_scan_at / checked_at / confidence / evidence[] / reason.

    ``status`` is the policy verdict, or PENDING while the check has not
    finished. A failed run is raised as an error by the caller, never reported
    as a verdict.
    """
    r = v.result
    status = r.decision.verdict.value if v.status == "complete" and r else "PENDING"
    out: dict[str, Any] = {
        "verification_id": v.id,
        "tracking_code": v.tracking_code,
        "status": status,
        "carrier_scan_at": v.delivered_at.isoformat(),
        "checked_at": v.checked_at.isoformat() if v.checked_at else None,
        "confidence": r.decision.confidence if r else None,
        "reason": _plain_reason(v),
        "synthetic": v.synthetic,
        "requires_approval": True,
        "recheck": {
            "state": v.recheck_state,
            "due_at": v.recheck_due_at.isoformat() if v.recheck_due_at else None,
            "provisional": _provisional(v),
        },
    }
    if include_evidence:
        out["evidence"] = [] if r is None else [
            {
                "frame_url": frame_url(base_url, v, e.frame_id),
                "frame_id": e.frame_id,
                "watermark_time": _iso(e.observation.watermark_ts) if e.observation else None,
                "parcel_visible": e.observation.parcel_visible if e.observation else None,
                "location": e.observation.location if e.observation else None,
                "source": e.source,
                "error": e.error,
            }
            for e in r.evidence
        ]
    return out


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _provisional(v: Verification) -> bool:
    return bool(
        v.result and v.result.decision.verdict.value == "DISPUTED" and v.recheck_state != "done"
    )


def _plain_reason(v: Verification) -> str:
    if v.result is None:
        return "The check has not finished yet."
    base = v.result.decision.reason
    if v.result.decision.verdict.value == "INCONCLUSIVE":
        return f"I can't see the step clearly enough to say. Please check. ({base})"
    if _provisional(v):
        return f"{base}. Provisional: a re-check is scheduled before any claim."
    return base
