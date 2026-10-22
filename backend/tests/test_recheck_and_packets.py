import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from countersign.evidence import MemorySink, S3Sink, build_packet
from countersign.ledger import Ledger
from countersign.main import create_app
from countersign.policy import Observation, Verdict, decide
from countersign.service import ServiceError, VerificationService
from countersign.trackers import EasyPostTrackers, delivered_at_from_result
from tests.test_api import T0, make_verifier


def service(visible, delay=3600, **kw):
    return VerificationService(make_verifier(visible, **kw), Ledger(), MemorySink(), recheck_delay_s=delay)


async def disputed(s):
    v, _ = s.start(source="manual", delivered_at=T0, tracking_code="EZ1")
    await s.run(v.id)
    return v


# ---- re-check loop --------------------------------------------------------

@pytest.mark.asyncio
async def test_timer_fires_recheck_after_delay():
    s = service(False, delay=0.05)
    v = await disputed(s)
    assert v.recheck_state == "scheduled" and v.recheck_due_at
    await asyncio.sleep(0.3)
    assert v.recheck_state == "done" and v.runs == 2 and len(v.result.frames) == 4


@pytest.mark.asyncio
async def test_stale_timer_skips_after_manual_recheck():
    s = service(False, delay=0.1)
    v = await disputed(s)
    await s.recheck(v.id)  # user clicked Re-check Now
    await asyncio.sleep(0.3)
    assert v.runs == 2  # the timer did not capture a third time


@pytest.mark.asyncio
async def test_verified_never_schedules_and_simulated_dispute_does_but_stays_unclaimable():
    s = service(True)
    v = await disputed(s)
    assert v.recheck_state == "none"
    s2 = service(False, source="synthetic")
    v2 = await disputed(s2)
    assert v2.recheck_state == "scheduled"  # demos can show the re-check
    await s2.recheck(v2.id)
    with pytest.raises(ServiceError, match="synthetic"):
        await s2.claim_packet(v2.id)


@pytest.mark.asyncio
async def test_failed_recheck_keeps_verdict_provisional_and_is_retryable():
    calls = {"n": 0}
    good = make_verifier(False)

    async def flaky(delivered_at, simulate, binding=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("ring 503")
        return await good(delivered_at, simulate, binding)

    s = VerificationService(flaky, Ledger(), MemorySink(), recheck_delay_s=3600)
    v = await disputed(s)
    await s.recheck(v.id)
    assert v.recheck_state == "scheduled" and "ring 503" in v.recheck_error
    with pytest.raises(ServiceError, match="provisional"):
        await s.claim_packet(v.id)
    await s.recheck(v.id)
    assert v.recheck_state == "done" and v.recheck_error is None


@pytest.mark.asyncio
async def test_recheck_unfinished_verification_refused():
    s = service(False)
    v, _ = s.start(source="manual", delivered_at=T0)
    with pytest.raises(ServiceError, match="not complete"):
        await s.recheck(v.id)


# ---- policy confidence ----------------------------------------------------

def _o(vis, conf, mins=2):
    return Observation(vis, conf, "porch", T0 + timedelta(minutes=mins))


def test_confidence_is_lowest_backing_frame():
    assert decide([_o(True, 0.99), _o(True, 0.85)], T0).confidence == 0.85
    assert decide([_o(False, 0.9), _o(False, 0.97, 3)], T0).confidence == 0.9


def test_inconclusive_has_no_confidence():
    assert decide([_o(True, 0.99), _o(False, 0.99)], T0).confidence is None


# ---- packets / SHA-256 ----------------------------------------------------

@pytest.mark.asyncio
async def test_manifest_hash_commits_to_every_frame():
    s = service(True)
    v = await disputed(s)
    manifest, frames, digest = build_packet(v)
    assert digest == hashlib.sha256(manifest).hexdigest()
    entries = json.loads(manifest)["frames"]
    assert len(entries) == len(frames) == 2
    for e in entries:
        assert e["sha256"] == hashlib.sha256(frames[e["file"]]).hexdigest()
        assert e["watermark_ts"]
    # reproducible
    assert build_packet(v)[2] == digest
    # tampering with a frame changes its recorded hash, hence the manifest hash
    v.result.frames[0] = type(v.result.frames[0])(b"tampered", "live", v.result.frames[0].captured_at)
    assert build_packet(v)[2] != digest


class StubS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


@pytest.mark.asyncio
async def test_s3_sink_encrypts_checksums_and_returns_manifest_hash():
    s = service(True)
    v = await disputed(s)
    client = StubS3()
    ref = await S3Sink("bkt", client).put_packet(v)
    assert ref.location == f"s3://bkt/evidence/{v.id}/"
    assert ref.sha256 == build_packet(v)[2]
    keys = {p["Key"] for p in client.puts}
    assert f"evidence/{v.id}/manifest.json" in keys and len(keys) == 3
    assert all(p["ServerSideEncryption"] == "AES256" and p["ChecksumAlgorithm"] == "SHA256" for p in client.puts)


def test_s3_sink_requires_bucket(monkeypatch):
    monkeypatch.delenv("COUNTERSIGN_EVIDENCE_BUCKET", raising=False)
    with pytest.raises(RuntimeError):
        S3Sink(client=StubS3())


# ---- HTTP: frames + recheck ----------------------------------------------

def test_frame_endpoint_serves_jpeg_bytes_and_404s():
    c = TestClient(create_app(verifier=make_verifier(True), ledger=Ledger(), sink=MemorySink()))
    vid = c.post("/verify", json={"delivered_at": T0.isoformat()}).json()["id"]
    fid = c.get(f"/verifications/{vid}").json()["result"]["evidence"][0]["frame_id"]
    r = c.get(f"/verifications/{vid}/frames/{fid}.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content == b"jpeg-0-0"
    assert c.get(f"/verifications/{vid}/frames/nope.jpg").status_code == 404


def test_http_recheck_unlocks_disputed_actions():
    c = TestClient(create_app(verifier=make_verifier(False), ledger=Ledger(), sink=MemorySink(), recheck_delay_s=3600))
    vid = c.post("/verify", json={"delivered_at": T0.isoformat()}).json()["id"]
    body = c.get(f"/verifications/{vid}").json()
    assert body["recheck_state"] == "scheduled"
    ap = {"action": "claim_draft", "approved": True, "approver": "Evan"}
    assert c.post(f"/verifications/{vid}/approvals", json=ap).status_code == 409
    assert c.post(f"/verifications/{vid}/recheck").json()["recheck_state"] == "done"
    assert c.post(f"/verifications/{vid}/approvals", json=ap).status_code == 200


# ---- EasyPost lookup ------------------------------------------------------

def _tracker(status="delivered", dt="2026-10-15T12:00:00Z"):
    return {"status": status, "tracking_details": [{"status": status, "datetime": dt}]}


@pytest.mark.asyncio
async def test_easypost_lookup_parses_delivered_and_sends_auth():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json=_tracker())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = await EasyPostTrackers("EZTEST", http).delivered_at("EZ4000000004", "USPS")
    assert got == datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    assert seen["body"] == {"tracker": {"tracking_code": "EZ4000000004", "carrier": "USPS"}}
    assert seen["auth"].startswith("Basic ")


@pytest.mark.asyncio
async def test_easypost_lookup_not_delivered_none_and_errors_raise(monkeypatch):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_tracker("in_transit")))) as http:
        assert await EasyPostTrackers("k", http).delivered_at("EZ1", None) is None
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401))) as http:
        with pytest.raises(RuntimeError, match="401"):
            await EasyPostTrackers("k", http).delivered_at("EZ1", None)
    monkeypatch.delenv("EASYPOST_API_KEY", raising=False)
    assert await EasyPostTrackers().delivered_at("EZ1", None) is None  # no key: no call


def test_delivered_at_requires_timezone():
    assert delivered_at_from_result(_tracker(dt="2026-10-15T12:00:00")) is None
    assert delivered_at_from_result({"tracking_details": []}) is None


def test_ledger_since_and_lookup():
    led = Ledger()
    v, _ = led.create(source="manual", delivered_at=T0, tracking_code="A")
    assert led.find_by_tracking_code("A") is v and led.find_by_tracking_code("B") is None
    assert led.list(since=v.created_at + timedelta(seconds=1)) == []
