import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from countersign.evidence import MemorySink
from countersign.frames import Frame
from countersign.ledger import Ledger
from countersign.main import create_app
from countersign.pipeline import FrameEvidence, VerificationResult
from countersign.policy import Observation, decide

T0 = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def make_verifier(visible: bool, source: str = "live", n: int = 2):
    async def run(delivered_at, simulate):
        frames, evidence, obs = [], [], []
        for i in range(n):
            ts = delivered_at + timedelta(minutes=1, seconds=i)
            f = Frame(f"jpeg-{i}".encode(), source, ts)  # type: ignore[arg-type]
            o = Observation(visible, 0.95, "porch", ts, source=source)  # type: ignore[arg-type]
            frames.append(f)
            obs.append(o)
            evidence.append(FrameEvidence(f.frame_id, source, ts, o))
        from countersign.policy import PolicyConfig

        d = decide(obs, delivered_at, PolicyConfig(allow_synthetic=True))
        return VerificationResult(d, delivered_at, "d1", evidence, frames, n)

    return run


def boom_verifier():
    async def run(delivered_at, simulate):
        raise RuntimeError("bedrock down")

    return run


def client(verifier, sink=None):
    return TestClient(create_app(verifier=verifier, ledger=Ledger(), sink=sink or MemorySink()))


def event(status="delivered", event_id="evt_1", dt="2026-10-15T12:00:00Z"):
    return {
        "id": event_id,
        "description": "tracker.updated",
        "result": {
            "status": status,
            "tracking_code": "EZ123",
            "tracking_details": [{"status": status, "datetime": dt}],
        },
    }


def verify(c, **kw):
    r = c.post("/verify", json={"delivered_at": T0.isoformat(), **kw})
    assert r.status_code == 202
    return r.json()["id"]


def test_health():
    assert client(make_verifier(True)).get("/healthz").json() == {"status": "ok"}


def test_verify_runs_pipeline_and_policy_sets_verdict():
    c = client(make_verifier(True))
    vid = verify(c)
    body = c.get(f"/verifications/{vid}").json()
    assert body["status"] == "complete"
    assert body["result"]["verdict"] == "VERIFIED"
    assert body["requires_approval"] is True


def test_pipeline_failure_recorded():
    c = client(boom_verifier())
    body = c.get(f"/verifications/{verify(c)}").json()
    assert body["status"] == "failed" and "bedrock down" in body["error"]


def test_unknown_verification_404():
    assert client(make_verifier(True)).get("/verifications/nope").status_code == 404


def test_naive_delivered_at_rejected():
    r = client(make_verifier(True)).post("/verify", json={"delivered_at": "2026-10-15T12:00:00"})
    assert r.status_code == 422


def test_webhook_delivered_creates_verification_and_dedupes():
    c = client(make_verifier(False))
    r1 = c.post("/webhooks/easypost", json=event())
    r2 = c.post("/webhooks/easypost", json=event())
    assert r1.status_code == 202 and not r1.json()["duplicate"]
    assert r2.json()["duplicate"] and r2.json()["id"] == r1.json()["id"]
    assert len(c.get("/verifications").json()) == 1
    assert c.get(f"/verifications/{r1.json()['id']}").json()["tracking_code"] == "EZ123"


def test_webhook_ignores_non_delivered_and_rejects_malformed():
    c = client(make_verifier(True))
    assert "ignored" in c.post("/webhooks/easypost", json=event("in_transit")).json()
    assert c.post("/webhooks/easypost", content=b"not json").status_code == 422
    assert c.post("/webhooks/easypost", json=event(dt="2026-10-15T12:00:00")).status_code == 422


def test_webhook_signature_enforced_when_secret_set(monkeypatch):
    monkeypatch.setenv("EASYPOST_WEBHOOK_SECRET", "s3cret")
    c = client(make_verifier(False))
    body = json.dumps(event()).encode()
    assert c.post("/webhooks/easypost", content=body).status_code == 401
    assert c.post(
        "/webhooks/easypost", content=body, headers={"x-hmac-signature": "hmac-sha256-hex=bad"}
    ).status_code == 401
    sig = "hmac-sha256-hex=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    ok = c.post("/webhooks/easypost", content=body, headers={"x-hmac-signature": sig})
    assert ok.status_code == 202


def approve(c, vid, action, approved=True, approver="Evan"):
    return c.post(
        f"/verifications/{vid}/approvals",
        json={"action": action, "approved": approved, "approver": approver},
    )


def test_claim_draft_requires_approval_then_works_for_disputed():
    c = client(make_verifier(False))
    vid = verify(c)
    r = c.post(f"/verifications/{vid}/claim-draft")
    assert r.status_code == 409 and r.json()["detail"]["error"] == "approval_required"

    assert approve(c, vid, "claim_draft", approved=False).status_code == 200
    assert c.post(f"/verifications/{vid}/claim-draft").status_code == 409

    assert approve(c, vid, "claim_draft").status_code == 200
    draft = c.post(f"/verifications/{vid}/claim-draft")
    assert draft.status_code == 200
    assert draft.json()["requires_approval"] is True
    assert draft.json()["carrier_delivered_at"] == T0.isoformat()
    # idempotent
    assert c.post(f"/verifications/{vid}/claim-draft").json() == draft.json()


def test_claim_draft_refused_for_non_disputed():
    c = client(make_verifier(True))  # VERIFIED
    vid = verify(c)
    assert approve(c, vid, "claim_draft").status_code == 409
    assert c.post(f"/verifications/{vid}/claim-draft").status_code == 409


def test_evidence_packet_gated_and_preserves_frames():
    sink = MemorySink()
    c = client(make_verifier(True), sink)
    vid = verify(c)
    assert c.post(f"/verifications/{vid}/evidence-packet").status_code == 409
    assert not sink.packets
    approve(c, vid, "evidence_packet")
    r = c.post(f"/verifications/{vid}/evidence-packet")
    assert r.status_code == 200 and r.json()["location"].endswith(vid)
    files = sink.packets[vid]
    assert "manifest.json" in files
    assert b"jpeg-0" in files.values()  # frame bytes stored unmodified
    # a second call does not re-upload
    sink.packets.clear()
    c.post(f"/verifications/{vid}/evidence-packet")
    assert not sink.packets


def test_synthetic_evidence_can_never_be_approved_or_acted_on():
    sink = MemorySink()
    # Policy opted in to synthetic here, so even a "DISPUTED" verdict exists.
    c = client(make_verifier(False, source="synthetic"), sink)
    vid = verify(c)
    body = c.get(f"/verifications/{vid}").json()
    assert body["synthetic"] is True
    for action in ("claim_draft", "evidence_packet"):
        assert approve(c, vid, action).status_code == 409
    assert c.post(f"/verifications/{vid}/claim-draft").status_code == 409
    assert c.post(f"/verifications/{vid}/evidence-packet").status_code == 409
    assert not sink.packets


def test_simulated_request_is_flagged_synthetic():
    c = client(make_verifier(True))
    vid = verify(c, simulate=True)
    assert c.get(f"/verifications/{vid}").json()["synthetic"] is True
    assert approve(c, vid, "evidence_packet").status_code == 409


def test_cannot_approve_pending_or_failed():
    c = client(boom_verifier())
    vid = verify(c)
    assert approve(c, vid, "evidence_packet").status_code == 409


def test_blank_approver_rejected():
    c = client(make_verifier(True))
    vid = verify(c)
    assert approve(c, vid, "evidence_packet", approver="").status_code == 422
    assert approve(c, vid, "evidence_packet", approver="   ").status_code == 422
