"""Deterministic delivery-verification policy.

The vision model only reports observations (is a parcel visible, where, how
confident, and the frame's watermark timestamp). Every verdict is computed
here with plain Python. Never let model output decide a verdict directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class Observation:
    """One vision-judge result for one frame.

    ``watermark_ts`` is the Ring-embedded timestamp. It places the frame in
    time but is never evidence that a parcel is present.
    """

    parcel_visible: bool
    confidence: float  # 0.0-1.0, as reported by the judge
    location: str | None = None  # e.g. "step", "porch"
    watermark_ts: datetime | None = None


@dataclass(frozen=True)
class PolicyConfig:
    min_confidence: float = 0.80  # observations below this are ignored
    min_positive_frames: int = 1  # confident "visible" frames for VERIFIED
    min_negative_frames: int = 2  # confident "not visible" frames for DISPUTED
    window_before: timedelta = timedelta(minutes=5)
    window_after: timedelta = timedelta(minutes=30)
    allowed_locations: frozenset[str] = frozenset({"step", "porch"})


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str
    positive_frames: int
    negative_frames: int
    considered_frames: int
    requires_approval: bool = True  # claims drafting always needs a human


def decide(
    observations: list[Observation],
    delivered_at: datetime,
    config: PolicyConfig = PolicyConfig(),
) -> Decision:
    """Return a verdict for a carrier "delivered" event at ``delivered_at``.

    Only frames with a watermark inside
    ``[delivered_at - window_before, delivered_at + window_after]`` and a
    confidence of at least ``config.min_confidence`` are considered.
    Positive frames must also show the parcel at an allowed location.
    Conflicting confident evidence is INCONCLUSIVE, never VERIFIED.
    """
    start = delivered_at - config.window_before
    end = delivered_at + config.window_after

    in_window = [
        o
        for o in observations
        if o.watermark_ts is not None
        and _comparable(o.watermark_ts, delivered_at)
        and start <= o.watermark_ts <= end
    ]
    confident = [o for o in in_window if o.confidence >= config.min_confidence]
    positive = [
        o
        for o in confident
        if o.parcel_visible and o.location in config.allowed_locations
    ]
    # Negative frames that dispute delivery must occur at or after carrier scan time.
    # Pre-delivery absence (porch empty before carrier arrives) is normal baseline,
    # not evidence of non-delivery.
    negative = [
        o
        for o in confident
        if not o.parcel_visible
        and o.watermark_ts is not None
        and o.watermark_ts >= delivered_at
    ]
    n_pos, n_neg, n_all = len(positive), len(negative), len(confident)

    def result(verdict: Verdict, reason: str) -> Decision:
        return Decision(verdict, reason, n_pos, n_neg, n_all)

    if n_all == 0:
        return result(Verdict.INCONCLUSIVE, "no confident frames in delivery window")
    if n_pos and n_neg:
        return result(Verdict.INCONCLUSIVE, "confident frames conflict")
    if n_pos >= config.min_positive_frames:
        return result(Verdict.VERIFIED, "parcel confidently visible in window")
    if n_neg >= config.min_negative_frames:
        return result(Verdict.DISPUTED, "parcel confidently absent in window")

    disallowed_locations = [
        o
        for o in confident
        if o.parcel_visible and o.location not in config.allowed_locations
    ]
    if disallowed_locations:
        locs = ", ".join(sorted({str(o.location) for o in disallowed_locations}))
        return result(
            Verdict.INCONCLUSIVE,
            f"parcel visible outside allowed delivery area ({locs})",
        )

    return result(Verdict.INCONCLUSIVE, "insufficient confident evidence")


def _comparable(a: datetime, b: datetime) -> bool:
    """Naive and aware datetimes cannot be compared; treat mixes as unusable."""
    return (a.tzinfo is None) == (b.tzinfo is None)
