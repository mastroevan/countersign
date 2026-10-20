"""Frame acquisition via WHEP (WebRTC HTTP Egress Protocol).

Uses aiortc to establish a WHEP live-view session with the Ring camera,
samples video frames, and extracts JPEGs with the Ring watermark intact.
Includes an offline test frame generator for local testing and simulations.
"""
from __future__ import annotations

import asyncio
import io
import os
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from countersign.ring_client import RingClient, RingClientError

# Check if aiortc is available
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    AIORTC_AVAILABLE = True
except ImportError:  # pragma: no cover
    AIORTC_AVAILABLE = False


class FrameCaptureError(RuntimeError):
    """Failed to acquire video frames from camera feed."""


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
    draw.rectangle((5, height - 28, width - 5, height - 6), fill=(0, 0, 0, 180))
    draw.text((10, height - 24), watermark_text, fill=(255, 255, 255))

    return image_to_jpeg(img)


async def grab_frames(
    client: RingClient,
    device_id: str,
    n_frames: int = 4,
    token: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[bytes]:
    """Capture frames from a Ring live-view WHEP endpoint using aiortc.

    Returns a list of JPEG-encoded byte strings.
    """
    if not AIORTC_AVAILABLE:  # pragma: no cover
        raise FrameCaptureError("aiortc package is required for WHEP frame capture.")

    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")

    session_id_or_url: str | None = None
    captured_jpegs: list[bytes] = []
    frame_ready = asyncio.Event()

    try:
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        if not pc.localDescription:
            raise FrameCaptureError("Failed to generate local SDP offer.")

        # Post offer to Ring WHEP endpoint
        answer_sdp, session_id_or_url = await client.start_whep(
            device_id=device_id,
            offer_sdp=pc.localDescription.sdp,
            token=token,
        )

        @pc.on("track")
        def on_track(track: Any) -> None:
            async def receive_loop() -> None:
                try:
                    while len(captured_jpegs) < n_frames:
                        frame = await track.recv()
                        # Convert aiortc VideoFrame to PIL Image
                        pil_img = frame.to_image()
                        captured_jpegs.append(image_to_jpeg(pil_img))
                        if len(captured_jpegs) >= n_frames:
                            frame_ready.set()
                            break
                except Exception:
                    frame_ready.set()

            asyncio.create_task(receive_loop())

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type="answer")
        )

        try:
            await asyncio.wait_for(frame_ready.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            if not captured_jpegs:
                raise FrameCaptureError(
                    f"Timed out after {timeout_seconds}s waiting for WHEP video frames."
                )

        return captured_jpegs

    finally:
        # Teardown WebRTC peer connection and remote WHEP session
        try:
            await pc.close()
        except Exception:
            pass

        if session_id_or_url:
            try:
                await client.stop_whep(
                    device_id=device_id,
                    session_id_or_url=session_id_or_url,
                    token=token,
                )
            except Exception:
                pass


async def get_camera_frames(
    client: RingClient,
    device_id: str,
    n_frames: int = 4,
    token: str | None = None,
    use_synthetic_fallback: bool = False,
    synthetic_has_parcel: bool = True,
    synthetic_watermark_ts: datetime | None = None,
) -> list[bytes]:
    """Acquire camera frames with optional synthetic fallback for offline simulation."""
    if use_synthetic_fallback or os.environ.get("COUNTERSIGN_OFFLINE_SIMULATION") == "true":
        return [
            create_synthetic_frame(
                has_parcel=synthetic_has_parcel,
                watermark_time=synthetic_watermark_ts or datetime.now(timezone.utc),
            )
            for _ in range(n_frames)
        ]

    try:
        return await grab_frames(client, device_id, n_frames=n_frames, token=token)
    except Exception as exc:
        if use_synthetic_fallback:
            return [
                create_synthetic_frame(
                    has_parcel=synthetic_has_parcel,
                    watermark_time=synthetic_watermark_ts or datetime.now(timezone.utc),
                )
                for _ in range(n_frames)
            ]
        raise FrameCaptureError(f"Failed to acquire live camera frames: {exc}") from exc
