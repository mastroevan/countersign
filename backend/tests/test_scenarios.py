import io
import json
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import uvicorn
from PIL import Image

import countersign.main as main_mod
from countersign.evidence import MemorySink
from countersign.ledger import Ledger
from countersign.main import create_app
from countersign.scenarios import (
    SCENARIOS,
    ScenarioError,
    build_event,
    create_easypost_tracker,
    format_event,
    local_tracker,
    main,
    run_scenario,
    sign,
)
from countersign.vision_judge import TOOL_NAME


class PixelBedrock:
    """Stands in for Bedrock: says "parcel" if the synthetic parcel's pixels are present."""

    def converse(self, **kw):
        img = kw["messages"][0]["content"][0]["image"]["source"]["bytes"]
        r, g, b = Image.open(io.BytesIO(img)).convert("RGB").getpixel((320, 310))
        visible = r > 160 and b < 130  # parcel box is (185, 142, 95); porch floor is grey
        inp = {
            "parcel_visible": visible,
            "confidence": 0.95,
            "location": "porch" if visible else "none",
            "watermark_timestamp": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
        }
        return {"output": {"message": {"content": [{"toolUse": {"name": TOOL_NAME, "input": inp}}]}},
                "ResponseMetadata": {"RequestId": "stub"}}


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setenv("COUNTERSIGN_SCENARIOS", "true")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "stub-model")
    monkeypatch.setenv("RECHECK_DELAY_S", "3600")
    monkeypatch.delenv("EASYPOST_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(main_mod, "make_client", lambda service: PixelBedrock())
    app = create_app(ledger=Ledger(), sink=MemorySink())  # the real default verifier
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    t = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


async def run(backend, name, **kw):
    out = io.StringIO()
    async with httpx.AsyncClient(timeout=30) as http:
        code = await run_scenario(name, backend, http, offline=True, out=out, timeout_s=30, **kw)
    return code, out.getvalue()


# ---- end to end, offline: real server, real default verifier, real SSE ------

@pytest.mark.asyncio
async def test_delivered_seen_ends_verified(backend):
    code, text = await run(backend, "delivered_seen")
    assert code == 0, text
    assert "STAGED" in text and "OFFLINE" in text
    for stage in ("webhook_received", "device_discovery", "frame_sampled", "bedrock_call", "judgment", "policy_rule", "verification_complete"):
        assert stage in text, (stage, text)
    assert "RESULT: VERIFIED" in text and "matches expected" in text


@pytest.mark.asyncio
async def test_delivered_not_seen_ends_disputed_with_recheck_pending(backend):
    code, text = await run(backend, "delivered_not_seen")
    assert code == 0, text
    assert "RESULT: DISPUTED" in text
    assert "recheck_scheduled" in text and "provisional; re-check due" in text


@pytest.mark.asyncio
async def test_delivered_not_seen_recheck_now_keeps_dispute(backend):
    code, text = await run(backend, "delivered_not_seen", recheck_now=True)
    assert code == 0, text
    assert "re-checking now" in text and "RESULT: DISPUTED" in text


@pytest.mark.asyncio
async def test_unreadable_ends_inconclusive_via_forced_timeout(backend):
    code, text = await run(backend, "unreadable")
    assert code == 0, text
    assert "forced timeout" in text and "camera_unavailable" in text
    assert "RESULT: INCONCLUSIVE" in text


@pytest.mark.asyncio
async def test_webhook_signature_is_sent_when_secret_configured(backend, monkeypatch):
    # The server in this fixture has no secret, so a signature header is simply ignored;
    # check the signing helper against the server's own verifier instead.
    from countersign.main import _valid_signature

    body = b'{"a":1}'
    assert _valid_signature("s3cret", body, {"x-hmac-signature": sign("s3cret", body)})
    assert not _valid_signature("other", body, {"x-hmac-signature": sign("s3cret", body)})


@pytest.mark.asyncio
async def test_backend_without_scenarios_flag_explains(backend, monkeypatch):
    monkeypatch.delenv("COUNTERSIGN_SCENARIOS")
    with pytest.raises(ScenarioError, match="COUNTERSIGN_SCENARIOS"):
        await run(backend, "delivered_seen")


# ---- units ---------------------------------------------------------------

def test_build_event_stages_scan_time_only_when_asked():
    tr = local_tracker(datetime(2020, 1, 1, tzinfo=timezone.utc))
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    staged = build_event(tr, now)
    kept = build_event(tr, None)
    assert staged["result"]["tracking_details"][-1]["datetime"] == "2026-10-20T12:00:00Z"
    assert kept["result"]["tracking_details"][-1]["datetime"] == "2020-01-01T00:00:00Z"
    assert staged["mode"] == "test" and staged["description"] == "tracker.updated"
    assert tr["tracking_details"][-1]["datetime"] == "2020-01-01T00:00:00Z"  # input not mutated


def test_format_event_is_one_line_and_hides_payload():
    ev = {"ts": "2026-10-20T12:00:01+00:00", "status": "ok", "stage": "bedrock_call",
          "data": {"model_id": "m", "latency_ms": 812, "request_id": None, "payload": {"big": "x" * 500}}}
    line = format_event(ev)
    assert "\n" not in line and "model_id=m" in line and "latency_ms=812" in line
    assert "payload" not in line and "request_id" not in line


@pytest.mark.asyncio
async def test_easypost_tracker_requires_a_test_key():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail("must not call"))) as http:
        with pytest.raises(ScenarioError, match="TEST key"):
            await create_easypost_tracker(http, "EZAK_live_key")


@pytest.mark.asyncio
async def test_easypost_tracker_creation_and_status_check():
    ok = {"id": "trk_1", "status": "delivered", "tracking_code": "EZ4000000004", "tracking_details": []}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(201, json=ok))) as http:
        assert (await create_easypost_tracker(http, "EZTK_test"))["id"] == "trk_1"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(201, json={**ok, "status": "in_transit"}))) as http:
        with pytest.raises(ScenarioError, match="expected delivered"):
            await create_easypost_tracker(http, "EZTK_test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="no"))) as http:
        with pytest.raises(ScenarioError, match="401"):
            await create_easypost_tracker(http, "EZTK_test")


@pytest.mark.asyncio
async def test_live_mode_setup_errors_are_clear():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail("no network expected")))
    async with http:
        with pytest.raises(ScenarioError, match="EASYPOST_API_KEY"):
            await run_scenario("delivered_seen", "http://x", http, env={}, out=io.StringIO())


@pytest.mark.asyncio
async def test_live_mode_needs_playground_device_id():
    tracker = {"id": "trk_1", "status": "delivered", "tracking_code": "EZ4000000004", "tracking_details": []}
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(201, json=tracker)))
    async with http:
        with pytest.raises(ScenarioError, match="RING_DEVICE_MOTION"):
            await run_scenario("delivered_not_seen", "http://x", http, env={"EASYPOST_API_KEY": "EZTK_t"}, out=io.StringIO())


@pytest.mark.asyncio
async def test_live_mode_sends_device_id_and_signed_webhook():
    sent = {}
    sse = "".join(
        f"data: {json.dumps(e)}\n\n"
        for e in [
            {"seq": 1, "ts": "2026-10-20T12:00:00+00:00", "stage": "verification_complete", "status": "ok", "data": {}},
        ]
    )

    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if "easypost.com" in u:
            return httpx.Response(201, json={"id": "trk_7", "status": "delivered", "tracking_code": "EZ4000000004",
                                             "tracking_details": [{"status": "delivered", "datetime": "2026-10-20T12:00:00Z"}]})
        if u.endswith("/api/bindings"):
            sent["binding"] = json.loads(req.content)
            return httpx.Response(201, json={})
        if u.endswith("/webhooks/easypost"):
            sent["sig"] = req.headers.get("x-hmac-signature")
            sent["body"] = req.content
            return httpx.Response(202, json={"id": "v1"})
        if "/api/trace" in u:
            return httpx.Response(200, text=sse)
        if u.endswith("/verifications/v1"):
            return httpx.Response(200, json={"result": {"verdict": "VERIFIED", "reason": "ok"}})
        return httpx.Response(404)

    env = {"EASYPOST_API_KEY": "EZTK_t", "RING_DEVICE_PACKAGE": "dev-pkg", "EASYPOST_WEBHOOK_SECRET": "s3"}
    out = io.StringIO()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        code = await run_scenario("delivered_seen", "http://x", http, env=env, out=out)
    assert code == 0, out.getvalue()
    assert sent["binding"] == {"key": "trk_7", "stream": "package", "device_id": "dev-pkg", "offline": False}
    assert sent["sig"] == sign("s3", sent["body"])
    assert "EasyPost test mode" in out.getvalue()


def test_cli_dry_run_and_unreachable_backend(capsys):
    assert main(["unreadable", "--dry-run"]) == 0
    assert "stream=timeout expected=INCONCLUSIVE" in capsys.readouterr().out
    assert main(["delivered_seen", "--offline", "--backend", "http://127.0.0.1:1", "--timeout", "2"]) == 2


def test_scenarios_cover_all_three_verdicts():
    assert {s.expected for s in SCENARIOS.values()} == {"VERIFIED", "DISPUTED", "INCONCLUSIVE"}
