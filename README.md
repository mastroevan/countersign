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

## Live trace and demo scenarios
`GET /api/trace` is a Server-Sent Events stream of pipeline stages (webhook, device discovery,
encryption check, WHEP session, sampled frames, Bedrock call with model ID / request ID / latency,
judgment, the policy rule that fired, re-check). Filter with `?verification_id=`, resume with
`Last-Event-ID`, or pass `follow=false` to just replay history. Events carry metadata only, never
image bytes.

```bash
# backend started with COUNTERSIGN_SCENARIOS=true
python -m countersign.scenarios delivered_seen      # Package stream  -> VERIFIED
python -m countersign.scenarios delivered_not_seen  # Motion stream   -> DISPUTED (re-check pending)
python -m countersign.scenarios unreadable          # forced timeout  -> INCONCLUSIVE
python -m countersign.scenarios delivered_seen --offline   # no EasyPost/Ring; synthetic frames
```
Live mode needs `EASYPOST_API_KEY` (test key, `EZTK...`) and `RING_DEVICE_PACKAGE` /
`RING_DEVICE_MOTION` (Playground device ids). **Staged and disclosed on screen:** the
tracker-to-stream wiring, the scan time (set to now unless `--use-tracker-time`), and, offline,
the frames. The EasyPost, Ring and Bedrock calls and the policy are real; offline frames are
synthetic and can never back a claim. Do not run a live tunnel webhook at the same time, or you
will get two verifications.
