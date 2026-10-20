import io
from datetime import datetime, timezone
import pytest
from PIL import Image

from countersign.frames import (
    create_synthetic_frame,
    image_to_jpeg,
    get_camera_frames,
    FrameCaptureError,
)
from countersign.ring_client import RingClient


def test_create_synthetic_frame():
    ts = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
    jpeg_bytes = create_synthetic_frame(
        has_parcel=True,
        parcel_location="porch",
        watermark_time=ts,
    )
    assert len(jpeg_bytes) > 0

    # Ensure PIL can open and parse it as a valid JPEG image
    img = Image.open(io.BytesIO(jpeg_bytes))
    assert img.format == "JPEG"
    assert img.size == (640, 480)


def test_image_to_jpeg():
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    raw = image_to_jpeg(img)
    assert len(raw) > 0
    read_img = Image.open(io.BytesIO(raw))
    assert read_img.format == "JPEG"


@pytest.mark.asyncio
async def test_get_camera_frames_synthetic():
    client = RingClient(token="dummy")
    frames = await get_camera_frames(
        client,
        device_id="dummy-dev",
        n_frames=3,
        use_synthetic_fallback=True,
        synthetic_has_parcel=True,
    )
    assert len(frames) == 3
    for frame in frames:
        img = Image.open(io.BytesIO(frame))
        assert img.format == "JPEG"
