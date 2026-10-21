from datetime import datetime, timedelta, timezone

import httpx
import pytest

from countersign.frames import Frame
from countersign.pipeline import verify_delivery
from countersign.policy import PolicyConfig, Verdict
from countersign.ring_client import RingClient, RingDeviceInaccessibleError
from countersign.vision_judge import TOOL_NAME

@pytest.fixture(autouse=True)
def _model(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")


T0 = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def tool_resp(visible=True, conf=0.95, loc="porch", ts=None):
    inp = {"parcel_visible": visible, "confidence": conf, "location": loc}
    if ts:
        inp["watermark_timestamp"] = ts.isoformat()
    return {"output": {"message": {"content": [{"toolUse": {"name": TOOL_NAME, "input": inp}}]}}}


class Bedrock:
    def __init__(self, *responses):
        self.responses = list(responses)

    def converse(self, **kw):
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def frames_fn(frames):
    async def fn(*a, **k):
        fn.kwargs = k
        return frames

    return fn


def ring_with(devices):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": devices}))
    return RingClient(token="t", http_client=httpx.AsyncClient(transport=transport))


GOOD_DEV = {"id": "d1", "attributes": {"configuration": {"e2e_encryption": {"enabled": False}}}}
ENC_DEV = {"id": "d2", "attributes": {"configuration": {"e2e_encryption": {"enabled": True}}}}


def live(at):
    return Frame(b"jpeg-" + at.isoformat().encode(), "live", at)


@pytest.mark.asyncio
async def test_live_verified_end_to_end():
    now = T0 + timedelta(minutes=1)
    fn = frames_fn([live(now), live(now + timedelta(seconds=1))])
    bedrock = Bedrock(tool_resp(ts=now), tool_resp(ts=now))
    res = await verify_delivery(T0, ring_with([GOOD_DEV]), bedrock, frames_fn=fn, n_frames=2)
    assert res.decision.verdict is Verdict.VERIFIED
    assert res.device_id == "d1"
    assert not res.partial_capture
    assert res.to_dict()["verdict"] == "VERIFIED"
    assert "jpeg" not in str(res.to_dict())


@pytest.mark.asyncio
async def test_encrypted_device_blocks_capture():
    called = False

    async def fn(*a, **k):
        nonlocal called
        called = True
        return []

    res = await verify_delivery(T0, ring_with([ENC_DEV]), Bedrock(), frames_fn=fn)
    assert not called, "WHEP must not open for an encrypted device"
    # No usable camera is INCONCLUSIVE with a plain reason, not an error or a verdict on the parcel.
    assert res.decision.verdict is Verdict.INCONCLUSIVE
    assert res.decision.rule == "camera_unavailable"
    assert "encrypted" in res.decision.reason and res.frames == []


@pytest.mark.asyncio
async def test_synthetic_path_skips_ring_and_is_not_verified():
    ring = RingClient(token="")  # any Ring call would raise
    n = 2
    bedrock = Bedrock(*[tool_resp(ts=T0 + timedelta(minutes=1)) for _ in range(n)])

    from countersign.frames import get_camera_frames

    res = await verify_delivery(
        T0, ring, bedrock, force_synthetic=True, n_frames=n, frames_fn=get_camera_frames
    )
    assert res.device_id == "simulated"
    assert res.decision.verdict is Verdict.INCONCLUSIVE
    assert res.decision.excluded_synthetic == n


@pytest.mark.asyncio
async def test_synthetic_opt_in_flagged():
    from countersign.frames import get_camera_frames

    res = await verify_delivery(
        T0,
        RingClient(token=""),
        Bedrock(tool_resp(ts=T0 + timedelta(minutes=1))),
        force_synthetic=True,
        n_frames=1,
        config=PolicyConfig(allow_synthetic=True),
        frames_fn=get_camera_frames,
    )
    assert res.decision.verdict is Verdict.VERIFIED
    assert res.decision.synthetic


@pytest.mark.asyncio
async def test_judge_failure_recorded_not_fatal():
    now = T0 + timedelta(minutes=1)
    fn = frames_fn([live(now), live(now + timedelta(seconds=1))])
    bedrock = Bedrock(RuntimeError("throttled"), tool_resp(ts=now))
    res = await verify_delivery(T0, ring_with([GOOD_DEV]), bedrock, frames_fn=fn, n_frames=2)
    assert res.decision.verdict is Verdict.VERIFIED
    assert [e.error is not None for e in res.evidence] == [True, False]


@pytest.mark.asyncio
async def test_watermark_disagreeing_with_capture_time_is_discarded():
    now = T0 + timedelta(minutes=1)
    fn = frames_fn([live(now)])
    # Model "read" a time 3 hours off from when we actually captured the frame.
    bedrock = Bedrock(tool_resp(ts=now + timedelta(hours=3)))
    res = await verify_delivery(T0, ring_with([GOOD_DEV]), bedrock, frames_fn=fn, n_frames=1)
    assert res.evidence[0].watermark_discarded
    assert res.decision.verdict is Verdict.INCONCLUSIVE
    assert res.decision.unusable_timestamps == 1


@pytest.mark.asyncio
async def test_partial_capture_flagged():
    now = T0 + timedelta(minutes=1)
    res = await verify_delivery(
        T0, ring_with([GOOD_DEV]), Bedrock(tool_resp(ts=now)),
        frames_fn=frames_fn([live(now)]), n_frames=4,
    )
    assert res.partial_capture and res.to_dict()["partial_capture"]


@pytest.mark.asyncio
async def test_offline_env_skips_ring_in_pipeline(monkeypatch):
    monkeypatch.setenv("COUNTERSIGN_OFFLINE_SIMULATION", "true")
    res = await verify_delivery(
        T0,
        RingClient(token=""),  # a Ring call would raise
        Bedrock(tool_resp(ts=T0 + timedelta(minutes=1))),
        n_frames=1,
        config=PolicyConfig(allow_synthetic=True),
    )
    assert res.device_id == "simulated"
    assert [f.source for f in res.frames] == ["synthetic"]


@pytest.mark.asyncio
async def test_capture_timeout_is_inconclusive():
    from countersign.frames import FrameCaptureError

    async def timeout(*a, **k):
        raise FrameCaptureError("No video frames received within 10s")

    res = await verify_delivery(T0, ring_with([GOOD_DEV]), Bedrock(), frames_fn=timeout)
    assert res.decision.verdict is Verdict.INCONCLUSIVE
    assert res.device_id == "d1"  # found the camera, then no frames arrived
    assert "No video frames" in res.decision.reason


@pytest.mark.asyncio
async def test_expired_token_stays_an_error_not_a_verdict():
    from countersign.ring_client import RingTokenExpiredError

    transport = httpx.MockTransport(lambda r: httpx.Response(401))
    ring = RingClient(token="t", http_client=httpx.AsyncClient(transport=transport))
    with pytest.raises(RingTokenExpiredError):
        await verify_delivery(T0, ring, Bedrock(), frames_fn=frames_fn([]))
