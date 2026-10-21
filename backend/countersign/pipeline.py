"""Delivery verification pipeline: device check -> frames -> vision -> policy.

``verify_delivery`` is the single entry point that the webhook, the MCP
server, and the UI call. The vision model only produces Observations; the
verdict always comes from ``policy.decide``.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo
from typing import Any

from countersign.frames import OFFLINE_ENV, Frame, get_camera_frames
from countersign.policy import Decision, Observation, PolicyConfig, decide
from countersign.ring_client import RingClient
from countersign.vision_judge import VisionJudgeError, judge_frame

SIMULATED_DEVICE_ID = "simulated"

FramesFn = Callable[..., Awaitable[list[Frame]]]


@dataclass(frozen=True)
class FrameEvidence:
    """What happened to one frame. The watermark is preserved for audit."""

    frame_id: str
    source: str
    captured_at: datetime
    observation: Observation | None  # None if the judge failed on this frame
    error: str | None = None
    watermark_skew_seconds: float | None = None
    watermark_discarded: bool = False  # read disagreed with capture time


@dataclass(frozen=True)
class VerificationResult:
    decision: Decision
    delivered_at: datetime
    device_id: str
    evidence: list[FrameEvidence]
    frames: list[Frame]  # raw JPEGs, kept for the (approval-gated) evidence packet
    frames_requested: int

    @property
    def partial_capture(self) -> bool:
        return len(self.frames) < self.frames_requested

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe summary. Never includes image bytes."""
        d = self.decision
        return {
            "verdict": d.verdict.value,
            "reason": d.reason,
            "requires_approval": d.requires_approval,
            "synthetic": d.synthetic,
            "positive_frames": d.positive_frames,
            "negative_frames": d.negative_frames,
            "considered_frames": d.considered_frames,
            "excluded_synthetic": d.excluded_synthetic,
            "unusable_timestamps": d.unusable_timestamps,
            "delivered_at": self.delivered_at.isoformat(),
            "device_id": self.device_id,
            "frames_requested": self.frames_requested,
            "partial_capture": self.partial_capture,
            "evidence": [_evidence_dict(e) for e in self.evidence],
        }


def _evidence_dict(e: FrameEvidence) -> dict[str, Any]:
    o = e.observation
    return {
        "frame_id": e.frame_id,
        "source": e.source,
        "captured_at": e.captured_at.isoformat(),
        "error": e.error,
        "watermark_skew_seconds": e.watermark_skew_seconds,
        "watermark_discarded": e.watermark_discarded,
        "parcel_visible": o.parcel_visible if o else None,
        "confidence": o.confidence if o else None,
        "location": o.location if o else None,
        "watermark_ts": o.watermark_ts.isoformat() if o and o.watermark_ts else None,
    }


async def verify_delivery(
    delivered_at: datetime,
    ring: RingClient,
    bedrock: Any,
    *,
    device_id: str | None = None,
    token: str | None = None,
    n_frames: int = 4,
    config: PolicyConfig = PolicyConfig(),
    device_tz: tzinfo | None = None,
    model_id: str | None = None,
    force_synthetic: bool = False,
    synthetic_has_parcel: bool = True,
    max_watermark_skew: timedelta = timedelta(seconds=120),
    frames_fn: FramesFn = get_camera_frames,
) -> VerificationResult:
    """Verify a carrier "delivered" event at ``delivered_at``.

    Live path: the device must be online and have ``e2e_encryption.enabled``
    explicitly false (``find_door_device`` fails closed) before a WHEP session
    is opened. Synthetic path skips the Ring API entirely.
    """
    force_synthetic = force_synthetic or os.environ.get(OFFLINE_ENV) == "true"
    if force_synthetic:
        resolved_id = SIMULATED_DEVICE_ID
    else:
        device = await ring.find_door_device(token=token, preferred_device_id=device_id)
        resolved_id = str(device["id"])

    frames = await frames_fn(
        ring,
        resolved_id,
        n_frames=n_frames,
        token=token,
        force_synthetic=force_synthetic,
        synthetic_has_parcel=synthetic_has_parcel,
        synthetic_watermark_ts=delivered_at if force_synthetic else None,
    )

    evidence = list(
        await asyncio.gather(
            *(
                _judge(bedrock, f, model_id, device_tz, max_watermark_skew)
                for f in frames
            )
        )
    )
    observations = [e.observation for e in evidence if e.observation is not None]
    decision = decide(observations, delivered_at, config)
    return VerificationResult(
        decision=decision,
        delivered_at=delivered_at,
        device_id=resolved_id,
        evidence=evidence,
        frames=frames,
        frames_requested=n_frames,
    )


async def _judge(
    bedrock: Any,
    frame: Frame,
    model_id: str | None,
    device_tz: tzinfo | None,
    max_skew: timedelta,
) -> FrameEvidence:
    try:
        obs = await asyncio.to_thread(
            judge_frame,
            bedrock,
            frame.jpeg,
            "jpeg",
            model_id,
            device_tz,
            frame.source,
        )
    except VisionJudgeError as exc:
        return FrameEvidence(frame.frame_id, frame.source, frame.captured_at, None, str(exc))
    except Exception as exc:  # Bedrock throttling/network: record, do not abort the batch
        return FrameEvidence(
            frame.frame_id, frame.source, frame.captured_at, None, f"{type(exc).__name__}: {exc}"
        )

    skew: float | None = None
    discarded = False
    # A model-read watermark that disagrees with when we captured the live
    # frame is more likely an OCR slip than a real offset: drop it.
    if frame.source == "live" and obs.watermark_ts is not None and obs.watermark_ts.tzinfo:
        skew = abs((obs.watermark_ts - frame.captured_at).total_seconds())
        if skew > max_skew.total_seconds():
            obs = replace(obs, watermark_ts=None)
            discarded = True
    return FrameEvidence(
        frame.frame_id, frame.source, frame.captured_at, obs, None, skew, discarded
    )
