import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError

from countersign.evidence import MemorySink
from countersign.ledger import Ledger
from countersign.main import create_app
from countersign.mcp_server import build_mcp
from countersign.service import VerificationService
from tests.test_api import T0, make_verifier


class FakeTrackers:
    def __init__(self, known=None):
        self.known = known or {}
        self.calls = []

    async def delivered_at(self, tracking_code, carrier):
        self.calls.append((tracking_code, carrier))
        return self.known.get(tracking_code)


def svc(visible=False, known=None, source="live"):
    return VerificationService(
        make_verifier(visible, source),
        Ledger(),
        MemorySink(),
        FakeTrackers({"EZ1": T0} if known is None else known),
        recheck_delay_s=3600,
    )


def mcp(service):
    return build_mcp(service, public_base_url="http://x")


async def call(client, name, **args):
    return (await client.call_tool(name, args)).data


@pytest.mark.asyncio
async def test_tool_surface_matches_blueprint_and_has_no_approval_tool():
    async with Client(mcp(svc())) as c:
        names = {t.name for t in await c.list_tools()}
    assert names == {"verify_delivery", "recheck_door", "get_delivery_ledger", "build_claim_packet"}


@pytest.mark.asyncio
async def test_verify_by_tracking_code_returns_blueprint_shape():
    s = svc(visible=True)
    async with Client(mcp(s)) as c:
        r = await call(c, "verify_delivery", tracking_code="EZ1", carrier="USPS")
    assert r["status"] == "VERIFIED"
    assert r["carrier_scan_at"] == T0.isoformat()
    assert r["checked_at"] and r["confidence"] == 0.95 and r["reason"]
    ev = r["evidence"][0]
    assert ev["frame_url"].startswith("http://x/verifications/") and ev["frame_url"].endswith(".jpg")
    assert ev["watermark_time"]
    assert r["requires_approval"] is True
    assert s.trackers.calls == [("EZ1", "USPS")]


@pytest.mark.asyncio
async def test_verify_is_idempotent_per_tracking_code():
    s = svc(visible=True)
    async with Client(mcp(s)) as c:
        a = await call(c, "verify_delivery", tracking_code="EZ1")
        b = await call(c, "verify_delivery", tracking_code="EZ1")
    assert a["verification_id"] == b["verification_id"]
    assert len(s.trackers.calls) == 1 and len(s.list()) == 1


@pytest.mark.asyncio
async def test_unknown_tracking_code_is_pending_not_a_verdict():
    async with Client(mcp(svc())) as c:
        r = await call(c, "verify_delivery", tracking_code="NOPE")
    assert r["status"] == "PENDING" and r["carrier_scan_at"] is None


@pytest.mark.asyncio
async def test_pipeline_failure_is_an_error_not_a_verdict():
    async def boom(*a):
        raise RuntimeError("ring token expired")

    s = VerificationService(boom, Ledger(), MemorySink(), FakeTrackers({"EZ1": T0}))
    async with Client(mcp(s)) as c:
        with pytest.raises(ToolError, match="no verdict.*ring token expired"):
            await c.call_tool("verify_delivery", {"tracking_code": "EZ1"})


@pytest.mark.asyncio
async def test_disputed_is_provisional_then_recheck_confirms_and_packet_is_gated():
    s = svc(visible=False)
    async with Client(mcp(s)) as c:
        first = await call(c, "verify_delivery", tracking_code="EZ1")
        assert first["status"] == "DISPUTED"
        assert first["recheck"] == {"state": "scheduled", "due_at": first["recheck"]["due_at"], "provisional": True}

        # Provisional: no packet, and approvals can't even be recorded yet.
        with pytest.raises(ToolError, match="re-check"):
            await c.call_tool("build_claim_packet", {"tracking_code": "EZ1"})
        with pytest.raises(Exception, match="re-check"):
            s.record_approval(first["verification_id"], "claim_draft", True, "Evan")

        again = await call(c, "recheck_door", tracking_code="EZ1")
        assert again["status"] == "DISPUTED" and again["recheck"]["provisional"] is False
        assert len(again["evidence"]) == 4  # frames from both looks

        with pytest.raises(ToolError, match="approval_required"):
            await c.call_tool("build_claim_packet", {"tracking_code": "EZ1"})
        vid = first["verification_id"]
        s.record_approval(vid, "claim_draft", True, "Evan")
        with pytest.raises(ToolError, match="approval_required"):  # one gate is not enough
            await c.call_tool("build_claim_packet", {"tracking_code": "EZ1"})
        assert s.get(vid).claim_draft is None and s.get(vid).evidence_location is None
        s.record_approval(vid, "evidence_packet", True, "Evan")
        pkt = await call(c, "build_claim_packet", tracking_code="EZ1")
    assert pkt["requires_approval"] is True
    assert len(pkt["sha256"]) == 64 and pkt["packet_url"].startswith("memory://")
    assert "EZ1" in pkt["draft_text"]


@pytest.mark.asyncio
async def test_recheck_with_parcel_now_present_is_inconclusive_and_not_claimable():
    s = svc(visible=[False, True])  # empty porch first, parcel appears on re-check
    async with Client(mcp(s)) as c:
        await call(c, "verify_delivery", tracking_code="EZ1")
        r = await call(c, "recheck_door", tracking_code="EZ1")
        assert r["status"] == "INCONCLUSIVE"
        with pytest.raises(ToolError, match="DISPUTED"):
            await c.call_tool("build_claim_packet", {"tracking_code": "EZ1"})


@pytest.mark.asyncio
async def test_new_evidence_after_recheck_clears_old_approvals():
    s = svc(visible=False)
    async with Client(mcp(s)) as c:
        vid = (await call(c, "verify_delivery", tracking_code="EZ1"))["verification_id"]
        await call(c, "recheck_door", tracking_code="EZ1")
        s.record_approval(vid, "claim_draft", True, "Evan")
        await call(c, "recheck_door", tracking_code="EZ1")
    assert s.get(vid).approvals == {}


@pytest.mark.asyncio
async def test_ledger_since_filter():
    s = svc(visible=True)
    async with Client(mcp(s)) as c:
        await call(c, "verify_delivery", tracking_code="EZ1")
        all_ = await c.call_tool("get_delivery_ledger", {})
        future = await c.call_tool("get_delivery_ledger", {"since": "2999-01-01"})
        assert len(all_.data) == 1 and "evidence" not in all_.data[0]
        assert future.data == []
        with pytest.raises(ToolError, match="ISO"):
            await c.call_tool("get_delivery_ledger", {"since": "last tuesday"})


@pytest.mark.asyncio
async def test_build_packet_for_unknown_code_errors():
    async with Client(mcp(svc())) as c:
        with pytest.raises(ToolError, match="No verification"):
            await c.call_tool("build_claim_packet", {"tracking_code": "NOPE"})


def test_mcp_mounted_over_streamable_http_on_fastapi():
    app = create_app(verifier=make_verifier(True), ledger=Ledger(), sink=MemorySink())
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    with TestClient(app) as http:
        r = http.post("/mcp/", json=init, headers=headers)
        assert r.status_code == 200, r.text
        assert "countersign" in r.text
        assert http.get("/healthz").status_code == 200
