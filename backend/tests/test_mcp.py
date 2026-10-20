import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError

from countersign.evidence import MemorySink
from countersign.ledger import Ledger
from countersign.main import create_app
from countersign.mcp_server import build_mcp
from countersign.service import VerificationService
from tests.test_api import make_verifier

WHEN = "2026-10-15T12:00:00Z"


def service(visible=False, source="live"):
    return VerificationService(make_verifier(visible, source), Ledger(), MemorySink())


@pytest.mark.asyncio
async def test_tool_surface_has_no_approval_tool():
    async with Client(build_mcp(service())) as c:
        names = {t.name for t in await c.list_tools()}
    assert names == {
        "verify_delivery",
        "get_verification",
        "list_verifications",
        "draft_claim",
        "store_evidence_packet",
    }
    assert not any("approv" in n for n in names)


@pytest.mark.asyncio
async def test_verify_returns_policy_verdict():
    async with Client(build_mcp(service(visible=True))) as c:
        res = await c.call_tool("verify_delivery", {"delivered_at": WHEN, "tracking_code": "EZ1"})
    data = res.data
    assert data["status"] == "complete"
    assert data["result"]["verdict"] == "VERIFIED"
    assert data["requires_approval"] is True


@pytest.mark.asyncio
async def test_naive_or_bad_timestamp_rejected():
    async with Client(build_mcp(service())) as c:
        for bad in ("2026-10-15T12:00:00", "yesterday"):
            with pytest.raises(ToolError):
                await c.call_tool("verify_delivery", {"delivered_at": bad})


@pytest.mark.asyncio
async def test_draft_claim_blocked_until_human_approves_via_service():
    svc = service(visible=False)
    async with Client(build_mcp(svc)) as c:
        vid = (await c.call_tool("verify_delivery", {"delivered_at": WHEN})).data["id"]
        with pytest.raises(ToolError, match="approval_required"):
            await c.call_tool("draft_claim", {"verification_id": vid})
        # Human approval happens outside MCP (dashboard/HTTP API).
        svc.record_approval(vid, "claim_draft", True, "Evan")
        draft = (await c.call_tool("draft_claim", {"verification_id": vid})).data
    assert draft["claim_type"] == "carrier_scanned_delivered_parcel_not_observed"


@pytest.mark.asyncio
async def test_simulated_run_cannot_produce_packet():
    svc = service(visible=True)
    async with Client(build_mcp(svc)) as c:
        vid = (
            await c.call_tool("verify_delivery", {"delivered_at": WHEN, "simulate": True})
        ).data["id"]
        with pytest.raises(ToolError, match="synthetic"):
            await c.call_tool("store_evidence_packet", {"verification_id": vid})


@pytest.mark.asyncio
async def test_unknown_verification_errors():
    async with Client(build_mcp(service())) as c:
        with pytest.raises(ToolError, match="not found"):
            await c.call_tool("get_verification", {"verification_id": "nope"})


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
        assert http.get("/healthz").status_code == 200  # REST still works alongside
