"""Deterministic delivery-verification policy.

The vision model only reports observations (is a parcel visible, where, how
confident, and the frame's watermark timestamp). Every verdict is computed
here with plain Python. Never let model output decide a verdict directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Literal


Source = Literal["live", "synthetic", "replay"]


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
    # "live" frames come from a real camera stream. "synthetic" frames are
    # generated for offline simulation and must never back a real claim.
    source: Source = "live"
    frame_id: str | None = None  # content hash, ties the verdict to evidence


@dataclass(frozen=True)
class PolicyConfig:
    min_confidence: float = 0.80  # observations below this are ignored
    min_positive_frames: int = 1  # confident "visible" frames for VERIFIED
    min_negative_frames: int = 2  # confident "not visible" frames for DISPUTED
    window_before: timedelta = timedelta(minutes=5)
    window_after: timedelta = timedelta(minutes=30)
    # A parcel seen before the carrier scan may be an earlier parcel. Allow only
    # a little clock skew between the carrier scan and the camera.
    positive_skew: timedelta = timedelta(seconds=60)
    allowed_locations: frozenset[str] = frozenset({"step", "porch"})
    # Synthetic frames are ignored unless a demo explicitly opts in. Even then
    # the Decision is flagged ``synthetic`` and the approval layer refuses it.
    allow_synthetic: bool = False


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str
    positive_frames: int
    negative_frames: int
    considered_frames: int
    requires_approval: bool = True  # claims drafting always needs a human
    synthetic: bool = False  # any considered frame was synthetic
    excluded_synthetic: int = 0  # synthetic frames dropped by config
    unusable_timestamps: int = 0  # frames with a missing/naive watermark
    # Lowest confidence among the frames that back the verdict (conservative);
    # None for INCONCLUSIVE, which has no backing frames.
    confidence: float | None = None
    # Stable id of the policy rule that fired, shown in the trace and ledger.
    rule: str = ""


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

    excluded_synthetic = 0
    usable: list[Observation] = []
    for o in observations:
        if o.source == "synthetic" and not config.allow_synthetic:
            excluded_synthetic += 1
        else:
            usable.append(o)
    unusable_ts = sum(
        1
        for o in usable
        if o.watermark_ts is None or not _comparable(o.watermark_ts, delivered_at)
    )

    in_window = [
        o
        for o in usable
        if o.watermark_ts is not None
        and _comparable(o.watermark_ts, delivered_at)
        and start <= o.watermark_ts <= end
    ]
    confident = [o for o in in_window if o.confidence >= config.min_confidence]
    positive = [
        o
        for o in confident
        if o.parcel_visible
        and o.location in config.allowed_locations
        and o.watermark_ts is not None
        and o.watermark_ts >= delivered_at - config.positive_skew
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

    synthetic = any(o.source == "synthetic" for o in confident)

    def result(verdict: Verdict, reason: str, rule: str) -> Decision:
        basis = positive if verdict is Verdict.VERIFIED else negative
        conf = (
            min(o.confidence for o in basis)
            if basis and verdict is not Verdict.INCONCLUSIVE
            else None
        )
        return Decision(
            verdict,
            reason,
            n_pos,
            n_neg,
            n_all,
            synthetic=synthetic,
            excluded_synthetic=excluded_synthetic,
            unusable_timestamps=unusable_ts,
            confidence=conf,
            rule=rule,
        )

    if n_all == 0:
        notes = []
        if unusable_ts:
            notes.append(f"{unusable_ts} with missing/unusable watermark")
        if excluded_synthetic:
            notes.append(f"{excluded_synthetic} synthetic excluded")
        suffix = f" ({', '.join(notes)})" if notes else ""
        return result(
            Verdict.INCONCLUSIVE,
            f"no confident frames in delivery window{suffix}",
            "no_confident_frames",
        )
    if n_pos and n_neg:
        return result(Verdict.INCONCLUSIVE, "confident frames conflict", "conflicting_frames")
    if n_pos >= config.min_positive_frames:
        return result(Verdict.VERIFIED, "parcel confidently visible in window", "parcel_visible")
    if n_neg >= config.min_negative_frames:
        return result(Verdict.DISPUTED, "parcel confidently absent in window", "parcel_absent_after_scan")

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
            "parcel_outside_delivery_area",
        )

    return result(Verdict.INCONCLUSIVE, "insufficient confident evidence", "insufficient_evidence")


def _comparable(a: datetime, b: datetime) -> bool:
    """Naive and aware datetimes cannot be compared; treat mixes as unusable."""
    return (a.tzinfo is None) == (b.tzinfo is None)


def camera_unavailable(reason: str) -> Decision:
    """INCONCLUSIVE for a camera that is offline, encrypted, or yields no frames.

    Absence of a picture is never evidence about the parcel. (An expired token
    is different: it is raised as an error, not turned into a verdict.)
    """
    return Decision(
        Verdict.INCONCLUSIVE,
        f"camera unavailable: {reason}",
        positive_frames=0,
        negative_frames=0,
        considered_frames=0,
        rule="camera_unavailable",
    )
