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

from countersign import trace
from countersign.frames import OFFLINE_ENV, Frame, FrameCaptureError, get_camera_frames
from countersign.policy import Decision, Observation, PolicyConfig, camera_unavailable, decide
from countersign.ring_client import RingClient, RingDeviceInaccessibleError
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
    config: PolicyConfig = PolicyConfig()  # the config the decision was made with

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
            "confidence": d.confidence,
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
    resolved_id = SIMULATED_DEVICE_ID if force_synthetic else (device_id or "unavailable")
    try:
        if force_synthetic:
            resolved_id = SIMULATED_DEVICE_ID
            trace.emit("device_discovery", "info", device_id=resolved_id, simulated=True)
        else:
            trace.emit("device_discovery", "started", preferred_device_id=device_id)
            device = await ring.find_door_device(token=token, preferred_device_id=device_id)
            resolved_id = str(device["id"])
            trace.emit("device_discovery", "ok", device_id=resolved_id)
            # find_door_device only returns devices with e2e_encryption.enabled == false
            trace.emit("encryption_check", "ok", device_id=resolved_id, e2e_encryption_enabled=False)

        frames = await frames_fn(
            ring,
            resolved_id,
            n_frames=n_frames,
            token=token,
            force_synthetic=force_synthetic,
            synthetic_has_parcel=synthetic_has_parcel,
            synthetic_watermark_ts=delivered_at if force_synthetic else None,
        )
    except (RingDeviceInaccessibleError, FrameCaptureError) as exc:
        # Offline, encrypted, or no frames: no picture is not evidence either way.
        # (An expired token is a different exception and propagates as an error.)
        trace.emit("camera", "error", error=str(exc))
        decision = camera_unavailable(str(exc))
        trace.emit("policy_rule", "ok", **_decision_data(decision))
        return VerificationResult(
            decision=decision,
            delivered_at=delivered_at,
            device_id=resolved_id,
            evidence=[],
            frames=[],
            frames_requested=n_frames,
            config=config,
        )

    for i, f in enumerate(frames):
        trace.emit(
            "frame_sampled", "ok", index=i, frame_id=f.frame_id, source=f.source,
            captured_at=f.captured_at, bytes=len(f.jpeg),
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
    trace.emit("policy_rule", "ok", **_decision_data(decision))
    return VerificationResult(
        decision=decision,
        delivered_at=delivered_at,
        device_id=resolved_id,
        evidence=evidence,
        frames=frames,
        frames_requested=n_frames,
        config=config,
    )


def _decision_data(d: Decision) -> dict[str, Any]:
    return {
        "verdict": d.verdict.value,
        "rule": d.rule,
        "reason": d.reason,
        "confidence": d.confidence,
        "positive_frames": d.positive_frames,
        "negative_frames": d.negative_frames,
        "considered_frames": d.considered_frames,
        "synthetic": d.synthetic,
    }


def combine_results(first: VerificationResult, second: VerificationResult) -> VerificationResult:
    """Merge two capture runs for one delivery and re-run the policy over ALL
    observations. Verdicts stay policy-derived: e.g. an empty porch followed by
    a visible parcel is a conflict (INCONCLUSIVE), never an automatic DISPUTED."""
    evidence = first.evidence + second.evidence
    observations = [e.observation for e in evidence if e.observation is not None]
    return VerificationResult(
        decision=decide(observations, first.delivered_at, first.config),
        delivered_at=first.delivered_at,
        device_id=second.device_id,
        evidence=evidence,
        frames=first.frames + second.frames,
        frames_requested=first.frames_requested + second.frames_requested,
        config=first.config,
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
        trace.emit("judgment", "error", frame_id=frame.frame_id, error=str(exc))
        return FrameEvidence(frame.frame_id, frame.source, frame.captured_at, None, str(exc))
    except Exception as exc:  # Bedrock throttling/network: record, do not abort the batch
        trace.emit("judgment", "error", frame_id=frame.frame_id, error=f"{type(exc).__name__}: {exc}")
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
            trace.emit("watermark_discarded", "info", frame_id=frame.frame_id, skew_seconds=skew)
            obs = replace(obs, watermark_ts=None)
            discarded = True
    trace.emit(
        "judgment", "ok", frame_id=frame.frame_id, parcel_visible=obs.parcel_visible,
        confidence=obs.confidence, location=obs.location, watermark_ts=obs.watermark_ts,
    )
    return FrameEvidence(
        frame.frame_id, frame.source, frame.captured_at, obs, None, skew, discarded
    )
