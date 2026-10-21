import asyncio
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from countersign import trace
from countersign.evidence import MemorySink
from countersign.ledger import Ledger
from countersign.main import create_app
from countersign.pipeline import verify_delivery
from countersign.policy import Verdict
from countersign.ring_client import RingClient
from countersign.service import VerificationService
from countersign.trace import TraceBus, sse_stream
from countersign.vision_judge import TOOL_NAME
from tests.test_api import T0, event, make_verifier
from tests.test_pipeline import GOOD_DEV, frames_fn, live, ring_with


def stages(bus, vid=None):
    return [(e.stage, e.status) for e in bus.history(vid=vid)]


# ---- bus ------------------------------------------------------------------

def test_publish_history_and_filters():
    bus = TraceBus()
    bus.publish("a", "s1")
    bus.publish("b", "s2", "error", x=1)
    bus.publish("a", "s3")
    assert [e.seq for e in bus.history()] == [1, 2, 3]
    assert [e.stage for e in bus.history(vid="a")] == ["s1", "s3"]
    assert [e.stage for e in bus.history(after_seq=2)] == ["s3"]


def test_history_is_bounded():
    bus = TraceBus(max_events=3)
    for i in range(5):
        bus.publish("a", f"s{i}")
    assert [e.stage for e in bus.history()] == ["s2", "s3", "s4"]


def test_payload_is_json_safe_and_never_carries_bytes():
    bus = TraceBus()
    ev = bus.publish("a", "s", when=T0, raw=b"\xff\xd8secret-image", verdict=Verdict.VERIFIED)
    json.dumps(ev.as_dict())
    assert ev.data["when"] == T0.isoformat()
    assert ev.data["raw"] == "<14 bytes>" and ev.data["verdict"] == "VERIFIED"


def test_emit_is_a_noop_when_unbound():
    trace.emit("anything", "ok", x=1)  # must not raise


@pytest.mark.asyncio
async def test_emit_follows_context_into_worker_threads():
    bus = TraceBus()
    with trace.bind(bus, "v1"):
        await asyncio.to_thread(trace.emit, "from_thread", "ok", n=1)
        await asyncio.gather(asyncio.to_thread(trace.emit, "t2", "ok"))
    assert [(e.verification_id, e.stage) for e in bus.history()] == [("v1", "from_thread"), ("v1", "t2")]
    trace.emit("after_unbind")
    assert len(bus.history()) == 2


# ---- SSE stream -----------------------------------------------------------

async def collect(gen, n):
    out = []
    async for chunk in gen:
        out.append(chunk)
        if len(out) >= n:
            break
    await gen.aclose()
    return out


def never():
    async def f():
        return False
    return f


@pytest.mark.asyncio
async def test_sse_replays_backlog_then_follows_live_without_duplicates():
    bus = TraceBus()
    bus.publish("a", "old1")
    bus.publish("a", "old2")
    gen = sse_stream(bus, never(), keepalive_s=5)
    first = [await gen.__anext__() for _ in range(3)]  # retry + 2 backlog
    assert first[0].startswith("retry:")
    assert "id: 1\nevent: trace\n" in first[1] and "id: 2\n" in first[2]
    bus.publish("a", "live")
    chunk = await asyncio.wait_for(gen.__anext__(), 2)
    assert "id: 3\n" in chunk and '"stage": "live"' in chunk
    await gen.aclose()


@pytest.mark.asyncio
async def test_sse_resumes_after_last_event_id_and_filters_by_verification():
    bus = TraceBus()
    for v, st in [("a", "x1"), ("b", "y1"), ("a", "x2"), ("a", "x3")]:
        bus.publish(v, st)
    chunks = await collect(sse_stream(bus, never(), vid="a", last_event_id=1, follow=False), 99)
    ids = [c for c in chunks if c.startswith("id:")]
    assert [c.split("\n")[0] for c in ids] == ["id: 3", "id: 4"]


@pytest.mark.asyncio
async def test_sse_follow_false_ends_after_backlog():
    bus = TraceBus()
    bus.publish("a", "x")
    chunks = [c async for c in sse_stream(bus, never(), follow=False)]
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_sse_keepalive_and_disconnect():
    bus = TraceBus()
    state = {"gone": False}

    async def disconnected():
        return state["gone"]

    gen = sse_stream(bus, disconnected, keepalive_s=0.05)
    assert (await gen.__anext__()).startswith("retry:")
    assert await gen.__anext__() == ": keepalive\n\n"
    state["gone"] = True
    assert [c async for c in gen] == []
    assert bus._subs == []  # subscription cleaned up


@pytest.mark.asyncio
async def test_slow_client_gets_lagged_and_can_resume():
    bus = TraceBus()
    gen = sse_stream(bus, never(), keepalive_s=5)
    await gen.__anext__()  # retry; subscription now active
    from countersign import trace as t

    for i in range(t.SUBSCRIBER_QUEUE + 10):
        bus.publish("a", f"e{i}")
    await asyncio.sleep(0.05)  # let the loop deliver
    rest = []
    async for c in gen:
        rest.append(c)
    assert rest[-1].startswith("event: lagged")


# ---- real pipeline emits the demo stages in order -------------------------

class StubBedrock:
    def converse(self, **kw):
        inp = {
            "parcel_visible": True,
            "confidence": 0.95,
            "location": "porch",
            "watermark_timestamp": (T0 + timedelta(minutes=1)).isoformat(),
        }
        return {
            "output": {"message": {"content": [{"toolUse": {"name": TOOL_NAME, "input": inp}}]}},
            "ResponseMetadata": {"RequestId": "req-123"},
            "usage": {"inputTokens": 900, "outputTokens": 40},
        }


@pytest.mark.asyncio
async def test_pipeline_trace_follows_demo_script(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "model-x")
    bus = TraceBus()
    now = T0 + timedelta(minutes=1)
    with trace.bind(bus, "v1"):
        await verify_delivery(T0, ring_with([GOOD_DEV]), StubBedrock(), n_frames=2,
                              frames_fn=frames_fn([live(now), live(now)]))
    names = [e.stage for e in bus.history()]
    order = ["device_discovery", "encryption_check", "frame_sampled", "bedrock_call", "judgment", "policy_rule"]
    positions = [names.index(s) for s in order]
    assert positions == sorted(positions)
    assert names.count("frame_sampled") == 2 and names.count("bedrock_call") == 2
    call = next(e for e in bus.history() if e.stage == "bedrock_call")
    assert call.data["model_id"] == "model-x" and call.data["request_id"] == "req-123"
    assert isinstance(call.data["latency_ms"], int)
    rule = bus.history()[-1]
    assert rule.stage == "policy_rule" and rule.data["verdict"] == "VERIFIED" and rule.data["rule"] == "parcel_visible"
    assert "jpeg" not in json.dumps([e.as_dict() for e in bus.history()])


@pytest.mark.asyncio
async def test_bedrock_failure_traced_as_error(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")

    class Boom:
        def converse(self, **kw):
            raise RuntimeError("throttled")

    bus = TraceBus()
    now = T0 + timedelta(minutes=1)
    with trace.bind(bus, "v1"):
        await verify_delivery(T0, ring_with([GOOD_DEV]), Boom(), n_frames=1, frames_fn=frames_fn([live(now)]))
    assert ("bedrock_call", "error") in stages(bus) and ("judgment", "error") in stages(bus)


@pytest.mark.asyncio
async def test_camera_unavailable_traced_then_policy_rule():
    bus = TraceBus()
    from tests.test_pipeline import ENC_DEV

    with trace.bind(bus, "v1"):
        await verify_delivery(T0, ring_with([ENC_DEV]), StubBedrock(), frames_fn=frames_fn([]))
    s = stages(bus)
    assert ("camera", "error") in s and s[-1] == ("policy_rule", "ok")
    assert bus.history()[-1].data["rule"] == "camera_unavailable"


# ---- service + HTTP -------------------------------------------------------

@pytest.mark.asyncio
async def test_service_traces_lifecycle_and_recheck_schedule():
    svc = VerificationService(make_verifier(False), Ledger(), MemorySink(), recheck_delay_s=3600)
    v, _ = svc.start(source="manual", delivered_at=T0)
    await svc.run(v.id)
    await svc.recheck(v.id)
    got = [e.stage for e in svc.trace.history(vid=v.id)]
    assert got == ["verification_started", "recheck_scheduled", "verification_complete",
                   "recheck_started", "recheck_complete"]


@pytest.mark.asyncio
async def test_service_traces_failure():
    async def boom(*a):
        raise RuntimeError("ring token expired")

    svc = VerificationService(boom, Ledger(), MemorySink())
    v, _ = svc.start(source="manual", delivered_at=T0)
    await svc.run(v.id)
    assert ("verification_failed", "error") in stages(svc.trace, v.id)


def parse_sse(text):
    return [json.loads(l[6:]) for l in text.splitlines() if l.startswith("data: ") and l != "data: {}"]


def test_trace_endpoint_streams_webhook_to_verdict():
    c = TestClient(create_app(verifier=make_verifier(True), ledger=Ledger(), sink=MemorySink()))
    ev = event()
    ev["mode"] = "test"
    vid = c.post("/webhooks/easypost", json=ev).json()["id"]
    r = c.get("/api/trace", params={"verification_id": vid, "follow": "false"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert [e["stage"] for e in events] == ["webhook_received", "verification_started", "verification_complete"]
    assert events[0]["data"]["payload"]["id"] == "evt_1"  # raw webhook shown for test mode
    # resume after the first event
    r2 = c.get("/api/trace", params={"verification_id": vid, "follow": "false"}, headers={"Last-Event-ID": str(events[0]["seq"])})
    assert [e["stage"] for e in parse_sse(r2.text)] == ["verification_started", "verification_complete"]


def test_live_mode_webhook_payload_is_not_echoed_to_trace():
    c = TestClient(create_app(verifier=make_verifier(True), ledger=Ledger(), sink=MemorySink()))
    ev = event()
    ev["mode"] = "production"
    vid = c.post("/webhooks/easypost", json=ev).json()["id"]
    first = parse_sse(c.get("/api/trace", params={"verification_id": vid, "follow": "false"}).text)[0]
    assert "payload" not in first["data"] and first["data"]["tracking_code"] == "EZ123"


def test_duplicate_webhook_does_not_duplicate_trace():
    c = TestClient(create_app(verifier=make_verifier(True), ledger=Ledger(), sink=MemorySink()))
    vid = c.post("/webhooks/easypost", json=event()).json()["id"]
    c.post("/webhooks/easypost", json=event())
    got = parse_sse(c.get("/api/trace", params={"verification_id": vid, "follow": "false"}).text)
    assert [e["stage"] for e in got].count("webhook_received") == 1


def test_bindings_endpoint_disabled_by_default(monkeypatch):
    monkeypatch.delenv("COUNTERSIGN_SCENARIOS", raising=False)
    c = TestClient(create_app(verifier=make_verifier(True), ledger=Ledger(), sink=MemorySink()))
    assert c.post("/api/bindings", json={"key": "trk_1", "stream": "package"}).status_code == 404


def test_binding_reaches_the_verifier_by_tracker_id(monkeypatch):
    monkeypatch.setenv("COUNTERSIGN_SCENARIOS", "true")
    seen = []
    inner = make_verifier(True)

    async def spy(delivered_at, simulate, binding=None):
        seen.append(binding)
        return await inner(delivered_at, simulate, binding)

    c = TestClient(create_app(verifier=spy, ledger=Ledger(), sink=MemorySink()))
    assert c.post("/api/bindings", json={"key": "trk_9", "stream": "motion", "device_id": "dev-m"}).status_code == 201
    ev = event()
    ev["result"]["id"] = "trk_9"
    c.post("/webhooks/easypost", json=ev)
    assert seen[0].stream == "motion" and seen[0].device_id == "dev-m"
