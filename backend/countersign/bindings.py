"""Demo scenario bindings: which stream a tracker is "wired" to.

The scenario wiring is staged (a test-mode tracker is bound to one Ring
Playground stream); the Ring and Bedrock calls and the judgment are live.
Bindings change which camera the pipeline reads, so the HTTP endpoint that
sets them is off unless ``COUNTERSIGN_SCENARIOS=true``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SCENARIOS_ENV = "COUNTERSIGN_SCENARIOS"
Stream = Literal["package", "motion", "timeout"]


@dataclass(frozen=True)
class StreamBinding:
    stream: Stream  # package: parcel on the step; motion: no parcel; timeout: no frames
    device_id: str | None = None  # Playground device for this stream (live mode)
    offline: bool = False  # synthetic frames shaped like the stream; never claimable
