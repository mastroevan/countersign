import io
from datetime import datetime, timezone
import pytest
from PIL import Image

from countersign.frames import (
    create_synthetic_frame,
    image_to_jpeg,
    get_camera_frames,
    Frame,
    FrameCaptureError,
)
import countersign.frames as frames_mod
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
async def test_force_synthetic_tags_frames():
    frames = await get_camera_frames(
        RingClient(token="dummy"), "dev", n_frames=3, force_synthetic=True
    )
    assert len(frames) == 3
    for f in frames:
        assert f.source == "synthetic"
        assert Image.open(io.BytesIO(f.jpeg)).format == "JPEG"
        assert len(f.frame_id) == 16


@pytest.mark.asyncio
async def test_offline_env_forces_synthetic(monkeypatch):
    monkeypatch.setenv("COUNTERSIGN_OFFLINE_SIMULATION", "true")
    frames = await get_camera_frames(RingClient(token="dummy"), "dev", n_frames=1)
    assert [f.source for f in frames] == ["synthetic"]


@pytest.mark.asyncio
async def test_live_failure_raises_without_fallback(monkeypatch):
    async def boom(*a, **k):
        raise FrameCaptureError("no stream")

    monkeypatch.delenv("COUNTERSIGN_OFFLINE_SIMULATION", raising=False)
    monkeypatch.setattr(frames_mod, "grab_frames", boom)
    with pytest.raises(FrameCaptureError):
        await get_camera_frames(RingClient(token="dummy"), "dev")


@pytest.mark.asyncio
async def test_live_failure_falls_back_when_requested(monkeypatch):
    async def boom(*a, **k):
        raise FrameCaptureError("no stream")

    monkeypatch.delenv("COUNTERSIGN_OFFLINE_SIMULATION", raising=False)
    monkeypatch.setattr(frames_mod, "grab_frames", boom)
    frames = await get_camera_frames(
        RingClient(token="dummy"), "dev", n_frames=2, fallback_to_synthetic=True
    )
    assert [f.source for f in frames] == ["synthetic", "synthetic"]


@pytest.mark.asyncio
async def test_live_success_passes_through(monkeypatch):
    live = [Frame(b"x", "live", datetime.now(timezone.utc))]

    async def ok(*a, **k):
        return live

    monkeypatch.delenv("COUNTERSIGN_OFFLINE_SIMULATION", raising=False)
    monkeypatch.setattr(frames_mod, "grab_frames", ok)
    assert await get_camera_frames(RingClient(token="dummy"), "dev") == live
