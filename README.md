# countersign
Hackathon project: verify carrier "delivered" scans against doorbell-camera evidence.

## Backend setup
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest tests/ && mypy countersign
uvicorn countersign.main:app --reload --port 8000
```

Environment: `RING_ACCESS_TOKEN`, `BEDROCK_MODEL_ID`, `COUNTERSIGN_DEVICE_TZ`
(IANA zone of the camera's watermark, e.g. `America/New_York`),
`EASYPOST_WEBHOOK_SECRET` (enforces HMAC when set), `COUNTERSIGN_EVIDENCE_BUCKET`,
`EASYPOST_API_KEY` (carrier lookup by tracking code), `RECHECK_DELAY_S` (600 default,
60 for demos), `PUBLIC_BASE_URL` (used in evidence frame URLs),
`COUNTERSIGN_OFFLINE_SIMULATION=true` (synthetic frames; can never back a claim).

MCP tools at `/mcp/` (Streamable HTTP): `verify_delivery`, `recheck_door`,
`get_delivery_ledger`, `build_claim_packet`. A DISPUTED verdict is provisional until
the re-check runs; claims and packets then need a human approval via
`POST /verifications/{id}/approvals`.
