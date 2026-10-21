"""Frame acquisition via WHEP (WebRTC HTTP Egress Protocol).

Uses aiortc to establish a WHEP live-view session with the Ring camera,
samples video frames, and extracts JPEGs with the Ring watermark intact.
Includes an offline test frame generator for local testing and simulations.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from countersign import trace
from countersign.policy import Source
from countersign.ring_client import RingClient

# Check if aiortc is available
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    AIORTC_AVAILABLE = True
except ImportError:  # pragma: no cover
    AIORTC_AVAILABLE = False


OFFLINE_ENV = "COUNTERSIGN_OFFLINE_SIMULATION"


class FrameCaptureError(RuntimeError):
    """Failed to acquire video frames from camera feed."""


@dataclass(frozen=True)
class Frame:
    """A JPEG plus provenance. ``source`` follows the frame through the policy."""

    jpeg: bytes
    source: Source
    captured_at: datetime  # server-side capture time, independent of the watermark

    @property
    def frame_id(self) -> str:
        return hashlib.sha256(self.jpeg).hexdigest()[:16]


def image_to_jpeg(image: Image.Image, quality: int = 85) -> bytes:
    """Convert a PIL Image to JPEG bytes."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def create_synthetic_frame(
    has_parcel: bool = True,
    parcel_location: str = "porch",
    watermark_time: datetime | str | None = None,
    device_name: str = "Front Door Camera",
    width: int = 640,
    height: int = 480,
) -> bytes:
    """Generate a realistic test frame with simulated porch and Ring watermark.

    Useful for offline testing, CI, and simulator fallback so tests never burn
    Ring Playground tokens.
    """
    img = Image.new("RGB", (width, height), color=(60, 65, 75))
    draw = ImageDraw.Draw(img)

    # Draw simulated porch / doorstep
    draw.rectangle((0, height // 2, width, height), fill=(130, 135, 140))  # ground/porch
    draw.rectangle((width // 4, height // 3, 3 * width // 4, height // 2), fill=(160, 120, 90))  # door mat/step

    if has_parcel:
        # Draw a parcel box on the step or porch
        if parcel_location == "porch":
            box_coords = (width // 2 - 40, height // 2 + 30, width // 2 + 50, height // 2 + 110)
        else:  # step
            box_coords = (width // 2 - 30, height // 3 + 20, width // 2 + 40, height // 2 - 10)

        draw.rectangle(box_coords, fill=(185, 142, 95), outline=(100, 70, 40), width=2)
        # Tape line across box
        draw.line(
            [(box_coords[0], (box_coords[1] + box_coords[3]) // 2), (box_coords[2], (box_coords[1] + box_coords[3]) // 2)],
            fill=(210, 180, 130),
            width=3,
        )

    # Format timestamp
    if isinstance(watermark_time, datetime):
        ts_str = watermark_time.strftime("%m/%d/%Y %I:%M:%S %p UTC")
    elif isinstance(watermark_time, str):
        ts_str = watermark_time
    else:
        ts_str = datetime.now(timezone.utc).strftime("%m/%d/%Y %I:%M:%S %p UTC")

    # Burn Ring watermark overlay: top-left or bottom-left
    # Ring format: "[Device Name] - [Timestamp] - Ring Developer Playground: simulated streams"
    watermark_text = f"Ring: {device_name} | {ts_str} | Ring Developer Playground: simulated streams"
    draw.rectangle((5, height - 28, width - 5, height - 6), fill=(0, 0, 0))
    draw.text((10, height - 24), watermark_text, fill=(255, 255, 255))

    return image_to_jpeg(img)


async def grab_frames(
    client: RingClient,
    device_id: str,
    n_frames: int = 4,
    token: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[Frame]:
    """Capture frames from a Ring live-view WHEP endpoint using aiortc.

    Returns between 1 and ``n_frames`` live frames. Fewer than requested means
    the stream stalled or errored mid-capture; callers can compare lengths.
    Raises FrameCaptureError if no frame at all arrived.
    """
    if not AIORTC_AVAILABLE:  # pragma: no cover
        raise FrameCaptureError("aiortc package is required for WHEP frame capture.")

    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")

    session_id_or_url: str | None = None
    frames: list[Frame] = []
    errors: list[Exception] = []
    done = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []

    async def receive_loop(track: Any) -> None:
        try:
            while len(frames) < n_frames:
                video_frame = await track.recv()
                frames.append(
                    Frame(
                        jpeg=image_to_jpeg(video_frame.to_image()),
                        source="live",
                        captured_at=datetime.now(timezone.utc),
                    )
                )
        except Exception as exc:  # track ended or decode failed
            errors.append(exc)
        finally:
            done.set()

    try:
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        if not pc.localDescription:
            raise FrameCaptureError("Failed to generate local SDP offer.")

        @pc.on("track")
        def on_track(track: Any) -> None:
            if track.kind == "video":
                tasks.append(asyncio.create_task(receive_loop(track)))

        answer_sdp, session_id_or_url = await client.start_whep(
            device_id=device_id,
            offer_sdp=pc.localDescription.sdp,
            token=token,
        )
        trace.emit("whep_session", "ok", device_id=device_id, state="created")
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type="answer"))

        try:
            await asyncio.wait_for(done.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            pass

        if not frames:
            detail = f": {errors[0]!r}" if errors else ""
            trace.emit("whep_session", "error", device_id=device_id, state="no_frames",
                       timeout_s=timeout_seconds, detail=detail.lstrip(": ") or None)
            raise FrameCaptureError(
                f"No video frames received within {timeout_seconds}s{detail}"
            )
        return frames

    finally:
        for task in tasks:
            task.cancel()
        try:
            await pc.close()
        except Exception:
            pass
        if session_id_or_url:
            await client.stop_whep(
                device_id=device_id, session_id_or_url=session_id_or_url, token=token
            )
            trace.emit("whep_session", "info", device_id=device_id, state="closed")


def synthetic_frames(
    n_frames: int, has_parcel: bool, watermark_ts: datetime | None
) -> list[Frame]:
    ts = watermark_ts or datetime.now(timezone.utc)
    return [
        Frame(
            jpeg=create_synthetic_frame(has_parcel=has_parcel, watermark_time=ts),
            source="synthetic",
            captured_at=ts,
        )
        for _ in range(n_frames)
    ]


async def forced_timeout_frames(*args: Any, **kwargs: Any) -> list[Frame]:
    """Scenario stand-in for a stream that never produces frames."""
    trace.emit("whep_session", "error", state="no_frames", detail="forced timeout (scenario)")
    raise FrameCaptureError("No video frames received (forced timeout scenario)")


async def get_camera_frames(
    client: RingClient,
    device_id: str,
    n_frames: int = 4,
    token: str | None = None,
    force_synthetic: bool = False,
    fallback_to_synthetic: bool = False,
    synthetic_has_parcel: bool = True,
    synthetic_watermark_ts: datetime | None = None,
) -> list[Frame]:
    """Acquire camera frames.

    ``force_synthetic`` (or ``COUNTERSIGN_OFFLINE_SIMULATION=true``) skips the
    camera entirely; ``fallback_to_synthetic`` substitutes synthetic frames if
    live capture fails. Synthetic frames are always tagged ``source="synthetic"``
    so the policy and approval layers can refuse to act on them.
    """

    def fake() -> list[Frame]:
        return synthetic_frames(n_frames, synthetic_has_parcel, synthetic_watermark_ts)

    if force_synthetic or os.environ.get(OFFLINE_ENV) == "true":
        return fake()
    try:
        return await grab_frames(client, device_id, n_frames=n_frames, token=token)
    except Exception as exc:
        if fallback_to_synthetic:
            return fake()
        raise FrameCaptureError(f"Failed to acquire live camera frames: {exc}") from exc
